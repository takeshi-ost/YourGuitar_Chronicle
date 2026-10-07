"""Private ownership dispute acceptance on disposable loopback PostgreSQL.

Only run(port) opens database connections. Import, compilation and collection do
not launch servers, install packages, bind sockets, or contact a cloud service.
The aggregate runner provides an authorized developer/CI PostgreSQL instance.
All users, accepted applications, guitars, PDFs and photographs are synthetic.
Fixture creation/failure injection use the database owner; every product action
uses the unchanged bootstrap/migration runtime role and canonical Accounts.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from io import BytesIO
from itertools import count
import json
import hashlib
import re
from threading import Barrier, Lock
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import psycopg
from psycopg import errors, sql

from postgres_event_claim_checks import structure
from postgres_media_claim_checks import BIG_ID, image_bytes, reject_new_rows
from postgres_ownership_workflow_checks import grants, rejected
from ygc import disputes
from ygc.admin_bootstrap_job import grant_first_admin
from ygc.claim_revision import ClaimConflict
from ygc.cloud_claims import CloudClaims
from ygc.cloud_disputes import CloudDisputes
from ygc.cloud_dispute_storage import OriginalUnavailable
from ygc.cloud_dispute_routes import dispute_router
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_notifications import CloudNotifications
from ygc.cloud_storage import ObjectReference
from ygc.cloud_owner import CloudOwner
from ygc.cloud_ownership import CloudOwnership
from ygc.db.postgres import PostgresSettings, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ServiceRestricted
from ygc.db.postgres_ownership import BoundRepository, PostgresOwnership
from ygc.db.postgres_queries import ObservationConnection
from ygc.platform_boundaries import ActorContext
from ygc.identity_platform import VerifiedIdentity

ISSUER = 'synthetic-private-dispute-contract'
PRIVATE = 'DISPUTE-PRIVATE-ORIGINAL-DO-NOT-PUBLISH'
SUMMARY = 'Applicant-proposed-private-summary'
PDF = b'%PDF-1.4 synthetic dispute proof\n%%EOF'
STAMP = '2026-06-01T12:00:00+00:00'
MAX_TOTAL = 256 * 1024 * 1024


def decimal(value, expected=None):
    assert isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]*', value), value
    if expected is not None:
        assert value == str(expected), (value, expected)
    return int(value)


def revision(value):
    assert isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), value


def private_projection(value, records):
    text = json.dumps(value, default=str)
    for account in records.values():
        assert account['app_user_id'] not in text
    for forbidden in ('identity_subject', 'identity_provider', 'date_of_birth',
                      'projection_version', 'storage_path', 'avatar_storage_path',
                      'object_scope', 'object_name', 'object_generation', 'byte_size', 'sha256',
                      '"content"', '"disabled"'):
        assert forbidden not in text, forbidden


class FrozenDatetime(datetime):
    instant = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


class PrivateStorage:
    """Synthetic generation-pinned storage; never contacts GCS or deletes proof."""
    def __init__(self):
        self.objects, self.fetched, self.deleted = {}, [], []
        self.put_calls, self.fail_on, self.fail_after_on, self.on_get = 0, None, None, None
        self.lock = Lock()

    def put(self, scope, data, *, content_type):
        assert scope == 'content'
        with self.lock:
            self.put_calls += 1
            number = self.put_calls
        if number == self.fail_on:
            raise RuntimeError('Synthetic private storage write failure')
        reference = ObjectReference(scope, 'media/' + format(number, '032x'),
                                    BIG_ID + number, len(data), content_type)
        self.objects[reference] = data
        if number == self.fail_after_on:
            raise RuntimeError('Synthetic upload committed but acknowledgement was lost')
        return reference

    def get(self, reference):
        self.fetched.append(reference)
        if self.on_get:
            self.on_get(reference)
        return self.objects[reference]

    def delete(self, reference):
        self.deleted.append(reference)
        raise AssertionError('Dispute originals must never be cleaned up automatically')


def reference_from_row(row):
    return ObjectReference(row['object_scope'], row['object_name'], row['object_generation'],
                           row['byte_size'], row['content_type'])


def insert_original(con, evidence, reference, data):
    con.execute('''INSERT INTO ownership_dispute_originals(evidence_id,object_scope,
        object_name,object_generation,byte_size,content_type,sha256,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
        (evidence, reference.scope, reference.name, reference.generation, reference.size,
         reference.content_type, hashlib.sha256(data).hexdigest(), STAMP))


class Workflow:
    def __init__(self, settings, owner, records, operations):
        self.settings, self.db_owner, self.records, self.operations = settings, owner, records, operations
        self.accounts = PostgresAccounts(settings)
        self.storage = PrivateStorage()
        self.service = CloudDisputes(settings, operations, self.storage)
        self.owners = CloudOwner(settings, operations)
        self.ownership = CloudOwnership(settings, operations)
        self.claims = CloudClaims(settings, operations)
        self.notifications = CloudNotifications(settings, operations)
        self.guitars = count(BIG_ID + 1000)
        self.claim_guitars = {}

    def actor(self, name):
        return self.records[name]['app_user_id']

    def user(self, name):
        return self.records[name]['id']

    def principal(self, name):
        return ActorContext(self.user(name), 'identity-platform', None, True, self.actor(name))

    def canonical(self, name, **changes):
        with connect(self.db_owner, 'accounts') as con:
            con.execute(sql.SQL('UPDATE account_records SET {} WHERE id=%s').format(
                sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)),
                (*changes.values(), self.user(name)))

    def guitar(self, *, owner='a', date='2026-01-01'):
        individual = next(self.guitars)
        with connect(self.db_owner, 'chronicle') as raw:
            raw.execute('''INSERT INTO individuals(id,manufacturer,model,serial_number,
                normalized_manufacturer,normalized_model,normalized_serial,created_at,updated_at)
                VALUES(%s,'Fender','Telecaster',%s,'fender','telecaster',%s,%s,%s)''',
                (individual, 'DISPUTE-' + str(individual), str(individual), STAMP, STAMP))
            # A complete, persistent identity Listing is independent of applicant
            # Claims. BAN and profile rebuilds must not erase the identity fixture.
            listing = raw.execute('''INSERT INTO claims(individual_id,author_user_id,
                claim_type,verification_status,occurred_at,created_at,updated_at)
                VALUES(%s,%s,'listing','positive',%s,%s,%s) RETURNING id''',
                (individual, self.user('admin'), date, STAMP, STAMP)).fetchone()['id']
            items = [('manufacturer', 'Fender'), ('model', 'Telecaster'),
                     ('serial_number', 'DISPUTE-' + str(individual))]
            if owner:
                items.append(('owner_user_id', str(self.user(owner))))
            for field, value in items:
                raw.execute('''INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at)
                    VALUES(%s,%s,%s,%s)''', (listing, field, value, STAMP))
            repo = BoundRepository(ObservationConnection(raw))
            repo._rebuild_individual_snapshot_in_connection(repo.connection, individual)
            if owner:
                # A completed initial Listing also materializes its owner's
                # profile link. Rebuild only reclassifies existing links; it
                # must not invent them for pending Acquire applicants.
                raw.execute('''INSERT INTO user_guitars(user_id,individual_id,ownership_status,
                    acquired_at,created_at,updated_at) VALUES(%s,%s,'current_owner',%s,%s,%s)''',
                    (self.user(owner), individual, date, STAMP, STAMP))
        return individual

    def acquire(self, name='b', *, guitar=None, created=STAMP, occurred='2026-04-01',
                source='user', accepted=True):
        guitar = self.guitar() if guitar is None else guitar
        with connect(self.db_owner, 'chronicle') as con:
            claim = con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,
                ownership_kind,ownership_source,value_text,verification_status,occurred_at,created_at,updated_at)
                VALUES(%s,%s,'ownership','acquire',%s,%s,'unverified',%s,%s,%s) RETURNING id''',
                (guitar, self.user(name), source, str(self.user(name)), occurred, created, created)).fetchone()['id']
            con.execute('''INSERT INTO claim_source_evidence(claim_id,evidence_type,effective_date,created_at)
                VALUES(%s,'acquisition_date',%s,%s)''', (claim, occurred, STAMP))
            if accepted:
                con.execute('''INSERT INTO acquire_applications(revision,applicant_id,individual_id,
                    original_individual_id,serial,challenge,expires_at,created_at,submitted_at,
                    acquisition_date,status,prompt_version,claim_id)
                    VALUES(%s,%s,%s,%s,'SYNTHETIC','SYNTHETIC',0,%s,%s,%s,'accepted',
                           'synthetic-disputes',%s)''',
                    (uuid.uuid4().hex, self.user(name), guitar, guitar, created, created, occurred, claim))
        self.claim_guitars[claim] = guitar
        return claim

    def pending(self, claim, name='a'):
        return next(row for row in self.owners.pending(self.actor(name), self.claim_guitars[claim])['items']
                    if row['id'] == str(claim))

    def decline(self, claim, name='a', reason='Synthetic owner decline'):
        row = self.pending(claim, name)
        self.owners.respond(self.actor(name), self.claim_guitars[claim], claim,
            {'revision': row['revision'], 'stance': 'negative', 'reason': reason})
        return self.option(claim)

    def option(self, claim, name='b'):
        result = self.service.option(self.actor(name), claim)
        decimal(result['claim_id'], claim)
        revision(result['revision'])
        for key in ('individual', 'applicant', 'owner'):
            if result[key] is not None:
                assert decimal(result[key]['id']) > 2**53
        private_projection(result, self.records)
        return result

    def detail(self, case, name='b', *, admin=False):
        result = self.service.detail(self.actor(name), int(case), admin=admin)
        assert decimal(result['id'], case) > 2**53
        assert decimal(result['version']) >= 1
        for rnd in result['rounds']:
            assert decimal(rnd['id']) > 2**53
            assert decimal(rnd['number']) >= 1
            for party in rnd['parties']:
                assert decimal(party['claim_id']) > 2**53
                assert decimal(party['user_id']) > 2**53
        for evidence in result['evidence']:
            for key in ('id', 'claim_id', 'author_id'):
                assert decimal(evidence[key]) > 2**53
            decimal(evidence['round_number'])
        private_projection(result, self.records)
        return result

    @staticmethod
    def open_data(option):
        return dict(revision=option['revision'], case_id=None, version=None, round_number=None,
                    explanation=PRIVATE, summary=SUMMARY)

    @staticmethod
    def submit_data(case):
        return dict(revision=None, case_id=case['id'], version=case['version'],
                    round_number=case['round']['number'], explanation=PRIVATE, summary=SUMMARY)

    def open(self, claim, name='b', *, content=PDF, data=None):
        result = self.service.submit(self.actor(name), claim,
            data or self.open_data(self.option(claim, name)), content, filename='unsafe-user-name.html')
        assert set(result) == {'detail'}
        return self.detail(result['detail']['id'], name)

    def submit(self, case, claim, name='a', *, data=None, content=b''):
        result = self.service.submit(self.actor(name), claim,
            data or self.submit_data(case), content, filename='unsafe-user-name.html')
        assert set(result) == {'detail'}
        return result['detail']

    @staticmethod
    def decision_data(case, action='owner', winner=None):
        return dict(version=case['version'], round_number=case['round']['number'],
                    action=action, reason='Synthetic reviewed decision',
                    winner_claim_id=str(winner) if winner is not None else None)

    def decide(self, case, action='owner', winner=None, name='admin'):
        result = self.service.decide(self.actor(name), int(case['id']),
                                    self.decision_data(case, action, winner))
        assert set(result) == {'detail'}
        return result['detail']

    def snapshot(self):
        with connect(self.settings, 'chronicle') as con:
            tables = [row['tablename'] for row in con.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
            result = {}
            for table in tables:
                # Hash raw bytes separately so 256 MiB quota fixtures do not
                # create huge hex/JSON copies or obscure the atomicity assertion.
                source = sql.Identifier(table)
                if table == 'ownership_dispute_evidence':
                    source = sql.SQL('''(SELECT id,dispute_id,claim_id,author_id,explanation,
                        summary,published_summary,published_at,filename,content_type,created_at,
                        octet_length(content) AS byte_count,encode(sha256(content),'hex') AS byte_hash
                        FROM ownership_dispute_evidence)''')
                result[table] = [row['value'] for row in con.execute(sql.SQL(
                    'SELECT to_jsonb(t) AS value FROM {} t ORDER BY to_jsonb(t)::text').format(source))]
            return result

    def unchanged(self, error, operation):
        before = self.snapshot()
        rejected(error, operation)
        assert self.snapshot() == before, 'Rejected dispute action left Chronicle writes behind'

    def current(self, guitar, name, *, former=()):
        with connect(self.settings, 'chronicle') as con:
            row = con.execute('SELECT * FROM individuals WHERE id=%s', (guitar,)).fetchone()
            assert row['current_owner_user_id'] == self.user(name)
            assert row['manufacturer'] == 'Fender' and row['model'] == 'Telecaster'
            assert row['serial_number'] == 'DISPUTE-' + str(guitar)
            relations = {row['user_id']: row['ownership_status'] for row in con.execute(
                'SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=%s', (guitar,))}
            assert relations.get(self.user(name)) == 'current_owner', relations
            for old in former:
                assert relations.get(self.user(old)) == 'former_owner', relations

    def mode(self, mode):
        actor = self.actor('admin')
        self.operations.set_mode(actor, mode=mode, message='', version=self.operations.details(actor)['version'])


def eligibility_and_acknowledgement_checks(w):
    assert disputes.WAIT_DAYS == 14, 'Acceptance requires the documented default 14-day threshold'
    with patch('ygc.disputes.datetime', FrozenDatetime):
        claim = w.acquire(created=(FrozenDatetime.instant - timedelta(days=14) + timedelta(microseconds=1)).isoformat())
        young = w.option(claim)
        assert young['wait_days'] == 14 and not young['can_appeal']
        w.unchanged(ValueError, lambda: w.open(claim))
        with connect(w.db_owner, 'chronicle') as con:
            con.execute('UPDATE claims SET created_at=%s WHERE id=%s',
                ((FrozenDatetime.instant - timedelta(days=14)).isoformat(), claim))
        ready = w.option(claim)
        assert ready['can_appeal'] and ready['revision'] != young['revision']
        w.unchanged(ClaimConflict, lambda: w.open(claim, data=w.open_data(young)))
        opened = w.open(claim)
        assert opened['status'] == 'open'
        w.current(w.claim_guitars[claim], 'a')  # Age alone never transfers ownership.

    for source, date, accepted in (('former_owner', '2026-04-01', True),
            ('automation', '2026-04-01', True), ('merged_listing', '2026-04-01', True),
            ('user', '2025-01-01', True), ('user', '2026-04-01', False)):
        claim = w.acquire(source=source, occurred=date, accepted=accepted)
        items = w.service.options(w.actor('b'), limit=50)['items']
        assert str(claim) not in {row['claim_id'] for row in items}, (source, date, accepted)
        w.unchanged((ValueError, GuitarMissing), lambda: w.open(claim))

    claim = w.acquire()
    before = w.option(claim)
    declined = w.decline(claim)
    assert declined['decline']['reason'] == 'Synthetic owner decline'
    assert declined['can_acknowledge'] and declined['can_appeal']
    w.unchanged(ClaimConflict, lambda: w.service.acknowledge(w.actor('b'), claim, {'revision': before['revision']}))
    w.unchanged(GuitarMissing, lambda: w.service.acknowledge(w.actor('c'), claim, {'revision': declined['revision']}))
    # Replacing an owner reason consumes the earlier acceptance revision too.
    w.decline(claim, reason='Replacement owner reason')
    w.unchanged(ClaimConflict, lambda: w.service.acknowledge(w.actor('b'), claim, {'revision': declined['revision']}))
    fresh = w.option(claim)
    result = w.service.acknowledge(w.actor('b'), claim, {'revision': fresh['revision']})
    assert set(result) == {'option'}
    assert result['option']['decline']['acknowledged_at']
    assert not result['option']['can_acknowledge'] and not result['option']['can_appeal']
    w.unchanged(ClaimConflict, lambda: w.service.acknowledge(w.actor('b'), claim, {'revision': fresh['revision']}))
    w.unchanged(ValueError, lambda: w.open(claim))


def privacy_and_round_checks(w):
    guitar = w.guitar()
    first, second = w.acquire(guitar=guitar), w.acquire('c', guitar=guitar)
    third = w.acquire('outsider', guitar=guitar)
    # Read both options before opening: the second must be refreshed before joining.
    stale = w.option(second, 'c')
    case = w.open(first)
    w.unchanged(ClaimConflict, lambda: w.open(second, 'c', data=w.open_data(stale)))
    joined = w.open(second, 'c')
    assert joined['id'] == case['id']
    owner, applicant, other = (w.detail(case['id'], name) for name in ('a', 'b', 'c'))
    admin = w.detail(case['id'], 'admin', admin=True)
    assert {r['claim_id'] for r in owner['claims']} == {str(first), str(second)}
    assert {r['claim_id'] for r in applicant['claims']} == {str(first)}
    assert {r['claim_id'] for r in other['claims']} == {str(second)}
    assert len(owner['evidence']) == 0 and len(admin['evidence']) == 2
    assert len(applicant['evidence']) == len(other['evidence']) == 1
    own = applicant['evidence'][0]
    assert own['explanation'] == PRIVATE and own['summary'] == SUMMARY
    assert own['filename'] == 'document.pdf' and own['content_type'] == 'application/pdf'
    evidence = int(own['id'])
    for name in ('a', 'c', 'outsider'):
        fetched = len(w.storage.fetched)
        w.unchanged(GuitarMissing, lambda: w.service.attachment(w.actor(name), evidence))
        assert len(w.storage.fetched) == fetched, 'Unauthorized request reached private storage'
    for name in ('b', 'admin'):
        assert w.service.attachment(w.actor(name), evidence, admin=name == 'admin') == {
            'content': PDF, 'content_type': 'application/pdf', 'filename': 'document.pdf'}
    w.unchanged(GuitarMissing, lambda: w.detail(case['id'], 'outsider'))
    assert str(case['id']) not in {row['id'] for row in w.service.list(w.actor('outsider'))['items']}
    publication = dict(version=admin['version'], round_number=admin['round']['number'],
                       summary='Reviewed purchase summary')
    w.unchanged(PermissionError, lambda: w.service.publish(w.actor('a'), evidence, publication))
    published = w.service.publish(w.actor('admin'), evidence, publication)['detail']
    seen = w.detail(case['id'], 'a')['evidence'][0]
    assert seen['published_summary'] == publication['summary']
    assert not {'explanation', 'summary', 'filename', 'content_type', 'has_attachment'} & set(seen)
    assert not any(row['id'] == own['id'] for row in w.detail(case['id'], 'c')['evidence'])
    w.unchanged(ClaimConflict, lambda: w.service.publish(w.actor('admin'), evidence, publication))
    w.unchanged((ValueError, ClaimConflict), lambda: w.service.publish(w.actor('admin'), evidence,
        publication | {'version': published['version']}))
    w.unchanged(ClaimConflict, lambda: w.submit(applicant, first))
    case = w.detail(case['id'], 'a')
    w.unchanged(ValueError, lambda: w.submit(case, first, 'b'))
    w.unchanged((PermissionError, GuitarMissing), lambda: w.submit(case, second, 'b'))
    w.unchanged(ValueError, lambda: w.decide(case, 'request_evidence'))
    case = w.submit(case, first)
    assert case['round']['phase'] == 'collecting'
    case = w.submit(case, second)
    assert case['round']['phase'] == 'reviewing'
    # A pre-existing competitor cannot join a reviewing round.
    w.unchanged(ClaimConflict, lambda: w.open(third, 'outsider'))
    # Both parties may submit only once, even with a newly fetched version.
    w.unchanged(ValueError, lambda: w.submit(case, first))
    previous = case
    case = w.decide(case, 'request_evidence')
    assert case['round']['number'] == '2' and case['round']['phase'] == 'collecting'
    assert len(case['rounds']) == 2 and all(p['submitted_at'] is None for p in case['round']['parties'])
    w.unchanged(ClaimConflict, lambda: w.submit(case, first, data=w.submit_data(previous)))
    # Original author and admin retain original evidence across all rounds.
    assert w.service.attachment(w.actor('b'), evidence)['content'] == PDF
    assert w.detail(case['id'], 'b')['evidence'][0]['explanation'] == PRIVATE
    return first, case, evidence


def private_storage_and_legacy_checks(w):
    claim = w.acquire()
    case = w.open(claim)
    evidence = int(case['evidence'][0]['id'])
    with connect(w.settings, 'chronicle') as con:
        row = con.execute('SELECT * FROM ownership_dispute_originals WHERE evidence_id=%s',
                          (evidence,)).fetchone()
        reference = reference_from_row(row)
        assert row['sha256'] == hashlib.sha256(PDF).hexdigest()
        assert row['byte_size'] == len(PDF) and row['object_scope'] == 'content'
        assert reference.generation > 1 and w.storage.objects[reference] == PDF
        assert con.execute('SELECT content FROM ownership_dispute_evidence WHERE id=%s',
                           (evidence,)).fetchone()['content'] is None

    # Storage retrieval happens while canonical account and service-mode locks
    # still fence revocation. NOWAIT probes require no timing-sensitive sleeps.
    def while_reading(_):
        for target, query, params in (
                ('accounts', 'SELECT id FROM account_records WHERE id=%s FOR UPDATE NOWAIT',
                 (w.user('b'),)),
                ('operations', 'SELECT id FROM settings WHERE id=1 FOR UPDATE NOWAIT', ())):
            def lock_probe():
                with connect(w.db_owner, target) as con:
                    con.execute(query, params)
            rejected(errors.LockNotAvailable, lock_probe)
    w.storage.on_get = while_reading
    try:
        assert w.service.attachment(w.actor('b'), evidence)['content'] == PDF
    finally:
        w.storage.on_get = None

    original = w.storage.objects.pop(reference)
    # A newer same-name object must never satisfy a missing pinned generation.
    replacement = replace(reference, generation=reference.generation + 1000)
    w.storage.objects[replacement] = original
    try:
        w.unchanged(OriginalUnavailable, lambda: w.service.attachment(w.actor('b'), evidence))
        assert w.storage.fetched[-1] == reference
    finally:
        w.storage.objects[reference] = original
    for corrupt in (original + b'x', b'x' * len(original)):
        w.storage.objects[reference] = corrupt
        w.unchanged(OriginalUnavailable, lambda: w.service.attachment(w.actor('b'), evidence))
    w.storage.objects[reference] = original

    # Owner-only fixture conversion stands in for a pre-migration BYTEA row.
    # The formerly referenced object is deliberately retained, never deleted.
    with connect(w.db_owner, 'chronicle') as con:
        con.execute('DELETE FROM ownership_dispute_originals WHERE evidence_id=%s', (evidence,))
        con.execute('UPDATE ownership_dispute_evidence SET content=%s WHERE id=%s', (PDF, evidence))
    fetched = len(w.storage.fetched)
    assert w.detail(case['id'])['evidence'][0]['has_attachment']
    assert w.service.attachment(w.actor('b'), evidence)['content'] == PDF
    assert w.service.attachment(w.actor('admin'), evidence, admin=True)['content'] == PDF
    for name in ('a', 'c', 'outsider'):
        w.unchanged(GuitarMissing, lambda: w.service.attachment(w.actor(name), evidence))
    assert len(w.storage.fetched) == fetched and reference in w.storage.objects

    # An unavailable backend may read old proof but must not silently put new
    # uploads back into BYTEA. Explicitly fail before any Chronicle mutation.
    unavailable = CloudDisputes(w.settings, w.operations, None)
    assert unavailable.attachment(w.actor('b'), evidence)['content'] == PDF
    new_claim = w.acquire()
    data = w.open_data(w.option(new_claim))
    w.unchanged((ValueError, RuntimeError), lambda: unavailable.submit(
        w.actor('b'), new_claim, data, PDF, filename='proof.pdf'))
    assert not w.storage.deleted


def byte_and_submission_limits(w):
    claim = w.acquire()
    for content in (b'', b'not an image or PDF', b'%PDF-' + b'x' * (disputes.MAX_BYTES - 4)):
        w.unchanged(ValueError, lambda: w.open(claim, content=content))
    option = w.option(claim)
    for changes in ({'explanation': ''}, {'explanation': 'x' * 8001}, {'summary': ''},
                    {'summary': 'x' * 4001}, {'case_id': 1}, {'version': 1}, {'round_number': 1},
                    {'viewer_id': str(w.user('a'))}, {'revision': 'x'}):
        w.unchanged(ValueError, lambda: w.open(claim, data=w.open_data(option) | changes))
    maximum = b'%PDF-' + b'x' * (disputes.MAX_BYTES - 5)
    case = w.open(claim, content=maximum)
    evidence = int(case['evidence'][0]['id'])
    assert len(w.service.attachment(w.actor('b'), evidence)['content']) == disputes.MAX_BYTES
    photo_claim = w.acquire()
    photo = w.open(photo_claim, content=image_bytes('JPEG'))
    downloaded = w.service.attachment(w.actor('b'), int(photo['evidence'][0]['id']))
    assert downloaded['filename'] == 'photo.jpg' and downloaded['content_type'] == 'image/jpeg'
    with Image.open(BytesIO(downloaded['content'])) as image:
        assert image.format == 'JPEG' and not image.getexif()

    # Mixed real BYTEA length and BIGINT reference sizes reach the exact 256 MiB
    # boundary. The 1 MiB legacy row remains within protective-backup limits.
    # Reuse immutable synthetic bytes in memory; every reference is distinct.
    quota_claim = w.acquire()
    quota = w.open(quota_claim)
    legacy_size = 1024 * 1024
    remaining = MAX_TOTAL - len(PDF) * 2 - legacy_size
    chunk = b'%PDF-' + b'x' * (disputes.MAX_BYTES - 5)
    with connect(w.db_owner, 'chronicle') as con:
        con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,claim_id,author_id,
            explanation,summary,filename,content_type,content,created_at) VALUES(%s,%s,%s,'Legacy quota',
            'Legacy quota','document.pdf','application/pdf',repeat('x',%s)::bytea,%s)''',
            (int(quota['id']), quota_claim, w.user('b'), legacy_size, STAMP))
        while remaining:
            size = min(disputes.MAX_BYTES, remaining)
            body = chunk if size == len(chunk) else chunk[:size]
            ref = w.storage.put('content', body, content_type='application/pdf')
            row = con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,
                claim_id,author_id,explanation,summary,filename,content_type,created_at)
                VALUES(%s,%s,%s,'Synthetic quota','Synthetic quota','document.pdf',
                'application/pdf',%s) RETURNING id''',
                (int(quota['id']), quota_claim, w.user('b'), STAMP)).fetchone()
            insert_original(con, row['id'], ref, body)
            remaining -= size
    uploads = w.storage.put_calls
    w.unchanged(ValueError, lambda: w.submit(w.detail(quota['id'], 'a'), quota_claim, content=PDF + b'x'))
    assert w.storage.put_calls == uploads, 'Over-quota proof reached private storage'
    quota = w.submit(w.detail(quota['id'], 'a'), quota_claim, content=PDF)
    with connect(w.settings, 'chronicle') as con:
        total = con.execute('''SELECT COALESCE(SUM(octet_length(e.content)),0) +
            COALESCE(SUM(o.byte_size),0) AS total FROM ownership_dispute_evidence e
            LEFT JOIN ownership_dispute_originals o ON o.evidence_id=e.id
            WHERE e.dispute_id=%s''', (int(quota['id']),)).fetchone()['total']
        assert total == MAX_TOTAL
    quota = w.decide(quota, 'request_evidence')
    w.unchanged(ValueError, lambda: w.submit(quota, quota_claim, 'b', content=PDF))

    count_claim = w.acquire()
    count_case = w.open(count_claim)
    with connect(w.db_owner, 'chronicle') as con:
        # One opening submission plus 99 synthetic old submissions reaches 100.
        con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,claim_id,author_id,
            explanation,summary,created_at) SELECT %s,%s,%s,'Historical synthetic',
            'Historical synthetic',%s FROM generate_series(1,99)''',
            (int(count_case['id']), count_claim, w.user('b'), STAMP))
    w.unchanged(ValueError, lambda: w.submit(w.detail(count_case['id'], 'a'), count_claim))


def legacy_backup_capacity_checks(w):
    from ygc.cloud_backup_job import save
    from ygc.cloud_backup_preflight import BackupCapacityError
    claim = w.acquire()
    case = w.open(claim)
    evidence = int(case['evidence'][0]['id'])
    with connect(w.db_owner, 'chronicle') as con:
        con.execute('DELETE FROM ownership_dispute_originals WHERE evidence_id=%s', (evidence,))
        con.execute('UPDATE ownership_dispute_evidence SET content=repeat(\'x\',%s)::bytea WHERE id=%s',
                    (disputes.MAX_BYTES, evidence))
    pending = w.acquire()
    data = w.open_data(w.option(pending))
    try:
        for expected in ('legacy_evidence_line_limit', 'legacy_evidence_restore_limit'):
            before, uploads = w.snapshot(), w.storage.put_calls
            for operation in (lambda: w.open(pending, data=data),
                              lambda: save(w.settings, w.storage, 'chronicle', 'synthetic-legacy-preflight')):
                error = rejected(BackupCapacityError, operation)
                assert error.stage == 'legacy_evidence_preflight' and error.code == expected
                assert w.snapshot() == before and w.storage.put_calls == uploads
                assert not w.storage.deleted
            if expected == 'legacy_evidence_line_limit':
                with connect(w.db_owner, 'chronicle') as con:
                    con.execute('UPDATE ownership_dispute_evidence SET content=NULL WHERE id=%s', (evidence,))
                    # Each old row fits the 8 MiB line limit; together their
                    # base64 alone exceeds the 32 MiB protective restore limit.
                    con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,
                        claim_id,author_id,explanation,summary,content,created_at)
                        SELECT %s,%s,%s,'Legacy aggregate','Legacy aggregate',
                        repeat('x',4194304)::bytea,%s FROM generate_series(1,7)''',
                        (int(case['id']), claim, w.user('b'), STAMP))
    finally:
        with connect(w.db_owner, 'chronicle') as con:
            con.execute("DELETE FROM ownership_dispute_evidence WHERE dispute_id=%s AND explanation='Legacy aggregate'",
                        (int(case['id']),))
            con.execute('UPDATE ownership_dispute_evidence SET content=%s WHERE id=%s', (PDF, evidence))


def authority_modes_and_projection_checks(w):
    claim = w.acquire()
    case = w.open(claim)
    evidence = int(case['evidence'][0]['id'])
    data = w.decision_data(case)
    for name in ('a', 'b', 'c', 'outsider'):
        w.unchanged(PermissionError, lambda: w.service.list(w.actor(name), admin=True))
        w.unchanged(PermissionError, lambda: w.service.detail(w.actor(name), int(case['id']), admin=True))
        w.unchanged(PermissionError, lambda: w.service.attachment(w.actor(name), evidence, admin=True))
        w.unchanged(PermissionError, lambda: w.service.decide(w.actor(name), int(case['id']), data))
    # Chronicle has no canonical role. Revoking the Accounts role is immediate,
    # even if the old admin tab retains a valid version and projection receipt.
    w.canonical('admin', role='member')
    try:
        w.unchanged(PermissionError, lambda: w.service.decide(w.actor('admin'), int(case['id']), data))
        w.unchanged(PermissionError, lambda: w.service.detail(w.actor('admin'), int(case['id']), admin=True))
    finally:
        w.canonical('admin', role='admin')
        w.accounts.drain_projection(limit=1000)

    for name, changes, restore in (
            ('b', {'ban_status': 'ban'}, {'ban_status': 'normal'}),
            ('b', {'ban_status': 'silent_ban'}, {'ban_status': 'normal'}),
            ('b', {'disabled': 1}, {'disabled': 0}),
            ('b', {'account_type': 'source'}, {'account_type': 'user'})):
        w.canonical(name, **changes)
        try:
            # Canonical rejection must not depend on asynchronous projection.
            w.unchanged(PermissionError, lambda: w.detail(case['id'], name))
            w.unchanged(PermissionError, lambda: w.service.attachment(w.actor(name), evidence))
            w.unchanged(PermissionError, lambda: w.service.options(w.actor(name)))
            w.unchanged((ValueError, PermissionError), lambda: w.decide(case))
        finally:
            w.canonical(name, **restore)
            w.accounts.drain_projection(limit=1000)

    for ban in ('ban', 'silent_ban'):
        w.canonical('b', ban_status=ban)
        try:
            w.accounts.drain_projection(limit=1000)
            w.unchanged(PermissionError, lambda: w.detail(case['id'], 'b'))
            assert w.detail(case['id'], 'admin', admin=True)['id'] == case['id']
            # An Admin may inspect the case, but cannot force a banned Acquire
            # to become the winner against the shared chronology evaluator.
            w.unchanged(ValueError, lambda: w.decide(case, 'applicant', claim))
            w.current(w.claim_guitars[claim], 'a')
        finally:
            w.canonical('b', ban_status='normal')
            w.accounts.drain_projection(limit=1000)

    # Ordinary profile changes produce stale projection fences, including for
    # a non-acting participant. Neither private reads nor decisions may run on
    # the earlier projection. The complete identity Listing remains available.
    w.canonical('a', display_name='Synthetic owner renamed')
    try:
        w.unchanged(ValueError, lambda: w.detail(case['id'], 'b'))
        w.unchanged(ValueError, lambda: w.decide(case))
    finally:
        w.accounts.drain_projection(limit=1000)
    w.current(w.claim_guitars[claim], 'a')
    assert w.detail(case['id'])['id'] == case['id']

    mode_cases = [w.open(w.acquire()), w.open(w.acquire())]
    w.mode('read_only')
    try:
        read = w.detail(case['id'], 'a')
        assert read['can_write'] is False
        assert all(not row['can_submit'] for row in read['round']['parties'])
        w.unchanged(ServiceRestricted, lambda: w.submit(read, claim))
        # Established Admin Operations access bypasses public service modes.
        assert w.detail(case['id'], 'admin', admin=True)['can_write'] is True
        assert w.decide(mode_cases[0])['status'] == 'resolved'
    finally:
        w.mode('normal')
    w.mode('offline')
    try:
        w.unchanged(ServiceRestricted, lambda: w.detail(case['id']))
        w.unchanged(ServiceRestricted, lambda: w.service.options(w.actor('b')))
        w.unchanged(ServiceRestricted, lambda: w.service.attachment(w.actor('b'), evidence))
        assert w.detail(case['id'], 'admin', admin=True)['can_write'] is True
        assert w.decide(mode_cases[1])['status'] == 'resolved'
    finally:
        w.mode('normal')
    w.mode('admin_only')
    try:
        w.unchanged(ServiceRestricted, lambda: w.detail(case['id'], 'b'))
        assert w.detail(case['id'], 'admin', admin=True)['id'] == case['id']
    finally:
        w.mode('normal')
    with connect(w.db_owner, 'operations') as maintenance:
        maintenance.execute('SELECT pg_advisory_xact_lock(79432190)')
        assert w.detail(case['id'], 'a')['id'] == case['id']
        w.unchanged(ClaimConflict, lambda: w.submit(case, claim))
        w.unchanged(ClaimConflict, lambda: w.decide(case))


def locked_owner_ban_projection_checks(w):
    # Use an ownerless identity Listing plus an actual A Acquire. Banning A
    # therefore removes the ownership basis, unlike a Listing naming A whose
    # author remains active. This exercises the real locked-owner conflict.
    guitar = w.guitar(owner=None)
    basis = w.acquire('a', guitar=guitar, occurred='2026-02-01')
    with connect(w.db_owner, 'chronicle') as raw:
        repo = BoundRepository(ObservationConnection(raw))
        # Approval records the accepted Acquire's profile link before rebuild,
        # exactly as the business path does; a raw status UPDATE skips that step.
        repo.admin_moderate_claim_in_connection(repo.connection, basis, 'positive')
    claim = w.acquire(guitar=guitar)
    case = w.open(claim)
    w.current(guitar, 'a')
    for ban in ('ban', 'silent_ban'):
        w.canonical('a', ban_status=ban)
        try:
            w.unchanged(PermissionError, lambda: w.detail(case['id'], 'a'))
            before = w.snapshot()
            rejected(errors.RaiseException, lambda: w.accounts.drain_projection(limit=1000))
            assert w.snapshot() == before, 'Failed BAN projection changed the locked ownership or receipt'
            w.unchanged(ValueError, lambda: w.detail(case['id'], 'b'))
            w.unchanged(ValueError, lambda: w.decide(case))
            w.current(guitar, 'a')
        finally:
            # This is owner-only synthetic fixture cleanup, not product policy:
            # safe fail-closed leaves the BAN projection awaiting reconciliation.
            w.canonical('a', ban_status='normal')
            w.accounts.drain_projection(limit=1000)
    assert w.detail(case['id'], 'b')['status'] == 'open'


def decisions_locks_and_reopen_checks(w):
    # Decisions are permitted with one side missing and after reopening with no
    # submissions. Under review is informative, never a decision prerequisite.
    for action in ('owner', 'applicant'):
        guitar = w.guitar()
        claim = w.acquire(guitar=guitar)
        case = w.open(claim)
        assert case['round']['phase'] == 'collecting'
        assert any(p['submitted_at'] is None for p in case['round']['parties'])
        w.unchanged(ValueError, lambda: w.decide(case, 'request_evidence'))
        old = case
        case = w.decide(case, action, claim if action == 'applicant' else None)
        assert case['status'] == 'resolved' and case['decision'] == action
        winner = 'b' if action == 'applicant' else 'a'
        w.current(guitar, winner, former=('a',) if action == 'applicant' else ())
        w.unchanged(ClaimConflict, lambda: w.decide(old, action, claim if action == 'applicant' else None))
        with connect(w.settings, 'chronicle') as con:
            row = con.execute('SELECT author_user_id,verification_status FROM claims WHERE id=%s', (claim,)).fetchone()
            assert row['author_user_id'] == w.user('b')
            assert row['verification_status'] == ('positive' if action == 'applicant' else 'negative')
            assert con.execute('SELECT COUNT(*) AS n FROM claim_admin_actions WHERE claim_id=%s', (claim,)).fetchone()['n'] == 1
        assert str(claim) not in {row['id'] for row in w.owners.pending(w.actor(winner), guitar)['items']}
        # Shared API and DB locks survive settlement for the disputed Claim.
        service = PostgresOwnership(w.settings)
        for name in ('a', 'b', 'c'):
            w.unchanged(ValueError, lambda: service.set_claim_response(claim, w.principal(name), 'positive'))
        for operation in ('positive', 'negative', 'delete'):
            w.unchanged((ValueError, errors.RaiseException), lambda: service.admin_moderate_claim(
                claim, w.principal('admin'), operation))
        for statement in ('UPDATE claims SET body=\'changed\' WHERE id=%s',
                          "UPDATE claims SET status='inactive' WHERE id=%s", 'DELETE FROM claims WHERE id=%s'):
            def mutate():
                with connect(w.settings, 'chronicle') as con:
                    con.execute(statement, (claim,))
            w.unchanged(errors.RaiseException, mutate)
        case = w.decide(case, 'reopen')
        assert case['status'] == 'open' and case['round']['number'] == '2'
        assert all(p['submitted_at'] is None for p in case['round']['parties'])
        w.current(guitar, winner)
        case = w.decide(case, 'owner')
        w.current(guitar, 'a')
        # Settling restores new ownership operations. A later actual transfer
        # invalidates reconsideration of the old case against a successor owner.
        view = w.ownership.view(w.actor('a'), guitar)
        transfer = w.ownership.create(w.actor('a'), guitar, {
            'revision': view['revision'], 'to_user_id': str(w.user('c'))})['transfer']
        transfer = w.ownership.detail(w.actor('c'), int(transfer['id']))
        w.ownership.resolve(w.actor('c'), int(transfer['id']), {'revision': transfer['revision'], 'action': 'accept'})
        w.current(guitar, 'c', former=('a',))
        w.unchanged(ValueError, lambda: w.decide(case, 'reopen'))
        w.unchanged(ValueError, lambda: service.set_claim_response(claim, w.principal('c'), 'positive'))

    # A second competing case cannot be reopened while another case is open.
    guitar = w.guitar()
    first, second = w.acquire(guitar=guitar), w.acquire('c', guitar=guitar)
    settled = w.decide(w.open(first), 'owner')
    opened = w.open(second, 'c')
    w.unchanged(ValueError, lambda: w.decide(settled, 'reopen'))
    assert w.detail(opened['id'], 'c')['status'] == 'open'

    # Original owner lock protects against pending transfer acceptance, new
    # ownership changes and ordinary moderation while non-ownership posts work.
    guitar = w.guitar()
    claim = w.acquire(guitar=guitar)
    view = w.ownership.view(w.actor('a'), guitar)
    transfer = w.ownership.create(w.actor('a'), guitar, {
        'revision': view['revision'], 'to_user_id': str(w.user('c'))})['transfer']
    pending = w.ownership.detail(w.actor('c'), int(transfer['id']))
    case = w.open(claim)
    w.unchanged((ClaimConflict, ValueError, errors.RaiseException), lambda: w.ownership.resolve(
        w.actor('c'), int(transfer['id']), {'revision': pending['revision'], 'action': 'accept'}))
    for kind in ('listing', 'ownership', 'identity_correction'):
        def new_claim():
            with connect(w.settings, 'chronicle') as con:
                con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s)''', (guitar, w.user('a'), kind, STAMP, STAMP))
        w.unchanged(errors.RaiseException, new_claim)
    event = w.claims.create(w.actor('b'), guitar, dict(claim_type='event',
        event_kind='performance', body='Synthetic ordinary event during dispute', occurred_at='2026-04-01'))['claim']
    assert event['verification_status'] == 'unverified'
    w.current(guitar, 'a')


def concurrency_checks(w):
    def race(*operations):
        gate = Barrier(len(operations))
        def run(operation):
            gate.wait(timeout=10)
            try:
                return ('accepted', operation())
            except ClaimConflict:
                return ('conflict', None)
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            return [future.result(timeout=30) for future in futures]

    # Distinct applicants may race: maintenance arbitration can reject one, but
    # its later refreshed retry joins exactly the one already-created case.
    guitar = w.guitar()
    first, second = w.acquire(guitar=guitar), w.acquire('c', guitar=guitar)
    first_data, second_data = w.open_data(w.option(first)), w.open_data(w.option(second, 'c'))
    results = race(lambda: w.open(first, data=first_data), lambda: w.open(second, 'c', data=second_data))
    assert any(state == 'accepted' for state, _ in results)
    cases = []
    for index, (state, row) in enumerate(results):
        if state != 'accepted':
            row = w.open((first, second)[index], ('b', 'c')[index])
        cases.append(row['id'])
    assert len(set(cases)) == 1
    with connect(w.settings, 'chronicle') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM ownership_disputes WHERE individual_id=%s', (guitar,)).fetchone()['n'] == 1
        assert con.execute('SELECT COUNT(*) AS n FROM ownership_dispute_claims WHERE dispute_id=%s', (int(cases[0]),)).fetchone()['n'] == 2

    # Exactly one application of the same write intent consumes the revision.
    claim = w.acquire()
    case = w.open(claim)
    data = w.submit_data(case)
    results = race(lambda: w.submit(case, claim, data=data), lambda: w.submit(case, claim, data=data))
    assert sorted(state for state, _ in results) == ['accepted', 'conflict']
    fresh = w.detail(case['id'], 'admin', admin=True)
    evidence = int(next(row for row in fresh['evidence'] if row['author_id'] == str(w.user('a')))['id'])
    publication = dict(version=fresh['version'], round_number=fresh['round']['number'], summary='One reviewed summary')
    publish = lambda: w.service.publish(w.actor('admin'), evidence, publication)
    assert sorted(state for state, _ in race(publish, publish)) == ['accepted', 'conflict']
    fresh = w.detail(case['id'], 'admin', admin=True)
    decision = lambda: w.decide(fresh)
    assert sorted(state for state, _ in race(decision, decision)) == ['accepted', 'conflict']
    w.current(w.claim_guitars[claim], 'a')
    with connect(w.settings, 'chronicle') as con:
        events = [row['kind'] for row in con.execute(
            'SELECT kind FROM ownership_dispute_events WHERE dispute_id=%s', (int(case['id']),))]
        assert events.count('summary_published') == events.count('resolved') == 1
        assert events.count('evidence_submitted') == 2


def atomicity_and_unknown_result_checks(w):
    claim = w.acquire()
    data = w.open_data(w.option(claim))
    for hook in ('fail_on', 'fail_after_on'):
        before = set(w.storage.objects)
        setattr(w.storage, hook, w.storage.put_calls + 1)
        try:
            w.unchanged(RuntimeError, lambda: w.open(claim, data=data))
            assert before.issubset(w.storage.objects)
            assert len(w.storage.objects) == len(before) + int(hook == 'fail_after_on')
            assert not w.storage.deleted
        finally:
            setattr(w.storage, hook, None)
    retained_orphan = False
    for table in ('ownership_disputes', 'ownership_dispute_claims', 'ownership_dispute_evidence',
                  'ownership_dispute_originals',
                  'ownership_dispute_rounds', 'ownership_dispute_round_parties',
                  'ownership_dispute_round_evidence', 'ownership_dispute_events', 'notifications'):
        before = w.snapshot()
        originals = set(w.storage.objects)
        with reject_new_rows(w.db_owner, table):
            rejected(errors.CheckViolation, lambda: w.open(claim, data=data))
        assert w.snapshot() == before, 'Opening failed to roll back ' + table
        assert originals.issubset(w.storage.objects) and not w.storage.deleted
        retained_orphan |= bool(set(w.storage.objects) - originals)
    assert retained_orphan, 'Failure injection did not reach a stored private original'
    case = w.open(claim, data=data)
    for table in ('ownership_dispute_evidence', 'ownership_dispute_originals',
                  'ownership_dispute_round_evidence', 'notifications'):
        before = w.snapshot()
        originals = set(w.storage.objects)
        with reject_new_rows(w.db_owner, table):
            rejected(errors.CheckViolation, lambda: w.submit(case, claim, content=PDF))
        assert w.snapshot() == before, 'Submission failed to roll back ' + table
        assert originals.issubset(w.storage.objects) and not w.storage.deleted
    for table in ('claim_admin_actions', 'ownership_dispute_events', 'notifications'):
        before = w.snapshot()
        with reject_new_rows(w.db_owner, table):
            rejected(errors.CheckViolation, lambda: w.decide(case, 'applicant', claim))
        assert w.snapshot() == before, 'Decision failed to roll back ' + table
        w.current(w.claim_guitars[claim], 'a')
    evidence = int(case['evidence'][0]['id'])
    publication = dict(version=case['version'], round_number=case['round']['number'], summary='Reviewed')
    with reject_new_rows(w.db_owner, 'notifications'):
        w.unchanged(errors.CheckViolation, lambda: w.service.publish(w.actor('admin'), evidence, publication))

    real_transaction = w.service.transaction
    @contextmanager
    def lost_acknowledgement(*args, **kwargs):
        with real_transaction(*args, **kwargs) as result:
            yield result
        raise RuntimeError('Synthetic connection loss after committed action')

    def lost(operation):
        with patch.object(w.service, 'transaction', lost_acknowledgement):
            rejected(RuntimeError, operation)
        committed = w.snapshot()
        originals = set(w.storage.objects)
        rejected(ClaimConflict, operation)
        assert w.snapshot() == committed, 'Unknown response retry duplicated a write'
        assert set(w.storage.objects) == originals and not w.storage.deleted
        with connect(w.settings, 'chronicle') as con:
            for row in con.execute('SELECT * FROM ownership_dispute_originals'):
                ref = reference_from_row(row)
                assert ref in w.storage.objects
                assert hashlib.sha256(w.storage.objects[ref]).hexdigest() == row['sha256']

    # Real commit followed by a dropped response, never a mock successful write.
    lost_claim = w.acquire()
    opening = w.open_data(w.option(lost_claim))
    lost(lambda: w.service.submit(w.actor('b'), lost_claim, opening, PDF, filename='evidence.pdf'))
    with connect(w.settings, 'chronicle') as con:
        case_id = con.execute('SELECT dispute_id FROM ownership_dispute_claims WHERE claim_id=%s', (lost_claim,)).fetchone()['dispute_id']
    case = w.detail(case_id, 'a')
    submitting = w.submit_data(case)
    lost(lambda: w.service.submit(w.actor('a'), lost_claim, submitting, PDF, filename='proof.pdf'))
    case = w.detail(case_id, 'admin', admin=True)
    evidence = int(case['evidence'][0]['id'])
    publication = dict(version=case['version'], round_number=case['round']['number'], summary='Recovered reviewed summary')
    lost(lambda: w.service.publish(w.actor('admin'), evidence, publication))
    case = w.detail(case_id, 'admin', admin=True)
    deciding = w.decision_data(case, 'applicant', lost_claim)
    lost(lambda: w.service.decide(w.actor('admin'), case_id, deciding))
    w.current(w.claim_guitars[lost_claim], 'b', former=('a',))
    ack_claim = w.acquire()
    option = w.decline(ack_claim)
    lost(lambda: w.service.acknowledge(w.actor('b'), ack_claim, {'revision': option['revision']}))


def notification_link_and_read_checks(w):
    guitar = w.guitar()
    first, second = w.acquire(guitar=guitar), w.acquire('c', guitar=guitar)
    declined = w.decline(first)
    with connect(w.settings, 'chronicle') as con:
        notice = con.execute("SELECT id FROM notifications WHERE claim_id=%s AND notification_type='ownership_decline'", (first,)).fetchone()['id']
    visible = next(row for row in w.notifications.list(w.actor('b'), limit=50)['items'] if row['id'] == str(notice))
    assert visible['destination'] == {'kind': 'dispute_option', 'claim_id': str(first)}
    before = w.snapshot()
    w.notifications.mark_read(w.actor('b'), notice)
    after = w.snapshot()
    assert {k: v for k, v in before.items() if k != 'notifications'} == {
        k: v for k, v in after.items() if k != 'notifications'}
    assert w.option(first)['revision'] == declined['revision']
    assert w.option(first)['decline']['acknowledged_at'] is None
    case = w.open(first)
    linked = next(row for row in w.notifications.list(w.actor('b'), limit=50)['items'] if row['id'] == str(notice))
    assert linked['destination'] == {'kind': 'dispute', 'case_id': case['id']}
    with connect(w.settings, 'chronicle') as con:
        history = {str(row['id']) for row in con.execute("""SELECT id FROM notifications
            WHERE individual_id=%s AND recipient_user_id=%s AND notification_type='ownership_dispute'""",
            (guitar, w.user('a')))}
    page = w.notifications.list(w.actor('a'), limit=50)
    assert history and all(row['destination'] == {'kind': 'dispute', 'case_id': case['id']}
        for row in page['items'] if row['id'] in history)
    assert PRIVATE not in json.dumps(page) and SUMMARY not in json.dumps(page)
    resolved = w.decide(case)
    other = w.open(second, 'c')
    assert other['id'] != resolved['id']
    # No case ID was historically stored in these notifications. Once two
    # cases exist for the owner, never silently point old history at the latest.
    page = w.notifications.list(w.actor('a'), limit=50)
    assert all(row['destination'] is None for row in page['items'] if row['id'] in history)
    linked = next(row for row in w.notifications.list(w.actor('b'), limit=50)['items'] if row['id'] == str(notice))
    assert linked['destination'] == {'kind': 'dispute', 'case_id': resolved['id']}
    before = w.snapshot()
    w.notifications.mark_all_read(w.actor('a'))
    after = w.snapshot()
    assert {k: v for k, v in before.items() if k != 'notifications'} == {
        k: v for k, v in after.items() if k != 'notifications'}


def pagination_and_http_checks(w):
    before = w.snapshot()
    for name, admin in (('a', False), ('b', False), ('admin', True)):
        ids, after = [], 0
        while True:
            page = w.service.list(w.actor(name), admin=admin, status='all', after=after, limit=2)
            assert set(page) == {'items', 'next_after', 'can_write', 'viewer_user_id'}
            decimal(page['viewer_user_id'], w.user(name))
            assert len(page['items']) <= 2
            private_projection(page, w.records)
            ids.extend(decimal(row['id']) for row in page['items'])
            if page['next_after'] is None:
                break
            after = decimal(page['next_after'])
        assert ids == sorted(set(ids), reverse=True)
    for method in (w.service.list, w.service.options):
        for query in ({'after': -1}, {'after': True}, {'after': 2**63}, {'limit': 0},
                      {'limit': 51}, {'limit': False}):
            w.unchanged(ValueError, lambda: method(w.actor('b'), **query))
    assert w.snapshot() == before, 'Private list/pagination mutated Chronicle state'

    class Verifier:
        accounts = w.accounts

        def verify(self, *, bearer_token):
            if bearer_token == 'unavailable':
                raise RuntimeError(PRIVATE)
            if bearer_token not in (*w.records, 'unverified'):
                raise PermissionError(PRIVATE)
            return VerifiedIdentity(ISSUER, 'b' if bearer_token == 'unverified' else bearer_token,
                                    '', bearer_token != 'unverified')

    api = FastAPI()
    api.include_router(dispute_router(Verifier(), w.service))
    base, admin = '/api/auth/ownership-disputes', '/api/auth/admin/ownership-disputes'
    claim = w.acquire()
    opening = w.open_data(w.option(claim))
    headers = lambda name: {'Authorization': 'Bearer ' + name}

    def checked(response, status):
        assert response.status_code == status, response.text
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Authorization'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['cross-origin-resource-policy'] == 'same-origin'
        if status != 200:
            assert PRIVATE not in response.text and ISSUER not in response.text
        return response

    with TestClient(api) as client:
        before = w.snapshot()
        for name, code in ((None, 401), ('invalid', 401), ('unverified', 403), ('unavailable', 503)):
            auth = headers(name) if name else {}
            checked(client.get(base, headers=auth), code)
            checked(client.get(base + '/options/' + str(claim), headers=auth), code)
        checked(client.get(admin, headers=headers('a')), 403)
        checked(client.get(base + '/options/' + str(claim), headers=headers('c')), 404)
        for suffix in ('?viewer_id=' + str(w.user('b')), '?unknown=1', '?limit=1&limit=2'):
            checked(client.get(base + suffix, headers=headers('b')), 400)
        assert w.snapshot() == before
        files = [('data', (None, json.dumps(opening))),
                 ('attachment', ('untrusted-user-name.html', PDF, 'application/pdf'))]
        path = base + '/options/' + str(claim) + '/evidence'
        # A real oversized legacy row triggers the operator-only capacity path.
        # HTTP reveals only the safe code, with no private aggregates or keys.
        with connect(w.db_owner, 'chronicle') as con:
            legacy = con.execute('''SELECT id,content FROM ownership_dispute_evidence
                WHERE content IS NOT NULL ORDER BY id LIMIT 1''').fetchone()
            assert legacy is not None
            con.execute("UPDATE ownership_dispute_evidence SET content=repeat('x',%s)::bytea WHERE id=%s",
                        (disputes.MAX_BYTES, legacy['id']))
        try:
            unchanged, uploads = w.snapshot(), w.storage.put_calls
            blocked = checked(client.post(path, headers=headers('b'), files=files), 409)
            assert blocked.json() == {'detail': {'code': 'dispute_storage_preflight_required'}}
            assert w.snapshot() == unchanged and w.storage.put_calls == uploads
        finally:
            with connect(w.db_owner, 'chronicle') as con:
                con.execute('UPDATE ownership_dispute_evidence SET content=%s WHERE id=%s',
                            (legacy['content'], legacy['id']))
        response = checked(client.post(path, headers=headers('b'), files=files), 200)
        case = response.json()['detail']
        assert decimal(case['id']) > 2**53 and case['evidence'][0]['explanation'] == PRIVATE
        committed = w.snapshot()
        checked(client.post(path, headers=headers('b'), files=files), 409)
        assert w.snapshot() == committed
        evidence = case['evidence'][0]['id']
        attachment_path = base + '/evidence/' + evidence + '/attachment'
        for name in ('a', 'c', 'outsider'):
            checked(client.get(attachment_path, headers=headers(name)), 404)
        raw = checked(client.get(attachment_path, headers=headers('b')), 200)
        assert raw.content == PDF and raw.headers['content-type'].startswith('application/pdf')
        assert raw.headers['content-disposition'] == 'attachment; filename="document.pdf"'
        checked(client.get(base + '/' + case['id'], headers=headers('outsider')), 404)
        checked(client.get(admin + '/' + case['id'], headers=headers('b')), 403)
        checked(client.get(admin + '/' + case['id'], headers=headers('admin')), 200)
        publication = dict(version=case['version'], round_number=case['round']['number'], summary='HTTP reviewed summary')
        publish_path = admin + '/evidence/' + evidence + '/publish'
        for extra, code in (({'Origin': 'https://untrusted.invalid'}, 403),
                            ({'Sec-Fetch-Site': 'cross-site'}, 403), ({'Content-Encoding': 'gzip'}, 400)):
            checked(client.post(publish_path, headers=headers('admin') | extra, json=publication), code)
        assert w.snapshot() == committed
        response = checked(client.post(publish_path, headers=headers('admin'), json=publication), 200)
        case = response.json()['detail']
        viewed = checked(client.get(base + '/' + case['id'], headers=headers('a')), 200).json()
        assert viewed['evidence'][0]['published_summary'] == publication['summary']
        assert PRIVATE not in json.dumps(viewed) and SUMMARY not in json.dumps(viewed)
        checked(client.get(attachment_path, headers=headers('a')), 404)
        data = w.decision_data(case, 'applicant', claim)
        response = checked(client.post(admin + '/' + case['id'] + '/decision', headers=headers('admin'), json=data), 200)
        assert response.json()['detail']['status'] == 'resolved'
        w.current(w.claim_guitars[claim], 'b', former=('a',))
        checked(client.post(admin + '/' + case['id'] + '/decision', headers=headers('admin'), json=data), 409)


def run(port):
    prefix = 'ygctest_disputes_' + uuid.uuid4().hex[:10] + '_'
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
            original_structure, original_grants = structure(owner, runtime), grants(settings)
            with connect(owner, 'accounts') as con:
                con.execute("SELECT setval(pg_get_serial_sequence('account_records','id'),%s,false)", (BIG_ID,))
            with connect(owner, 'chronicle') as con:
                for row in con.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall():
                    table = row['tablename']
                    sequence = con.execute('SELECT pg_get_serial_sequence(%s,\'id\') AS sequence', (table,)).fetchone() if con.execute(
                        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND column_name='id'", (table,)).fetchone() else None
                    if sequence and sequence['sequence']:
                        con.execute('SELECT setval(%s::regclass,%s,false)', (sequence['sequence'], BIG_ID + 10000))
            setup = PostgresAccounts(owner)
            records = {name: setup.ensure_identity(issuer=ISSUER, subject=name,
                display_name='Synthetic ' + name) for name in ('admin', 'a', 'b', 'c', 'outsider')}
            assert grant_first_admin(owner, records['admin']['app_user_id'], 'synthetic-dispute-test')
            setup.drain_projection(limit=1000)
            operations = PostgresOperations(settings)
            admin = records['admin']['app_user_id']
            operations.set_mode(admin, mode='normal', message='', version=operations.details(admin)['version'])
            w = Workflow(settings, owner, records, operations)
            eligibility_and_acknowledgement_checks(w)
            privacy_and_round_checks(w)
            private_storage_and_legacy_checks(w)
            byte_and_submission_limits(w)
            legacy_backup_capacity_checks(w)
            authority_modes_and_projection_checks(w)
            locked_owner_ban_projection_checks(w)
            decisions_locks_and_reopen_checks(w)
            concurrency_checks(w)
            atomicity_and_unknown_result_checks(w)
            notification_link_and_read_checks(w)
            pagination_and_http_checks(w)
            assert structure(owner, runtime) == original_structure, 'Dispute tests changed schema/runtime grants'
            assert grants(settings) == original_grants, 'Runtime privileges expanded'
            assert not w.storage.deleted, 'Dispute acceptance deleted private originals'
            print('PostgreSQL ownership disputes: exact IDs and 14-day threshold, chronology/decline '
                  'revision fences, private originals/reviewed summaries/applicant isolation, '
                  'legacy BYTEA/pinned private originals/mixed byte quotas/protective preflight, '
                  'joining/rounds/live canonical role/BAN/projection/mode fences, '
                  'incomplete-evidence decisions, settlement locks/transfer/reopen, races, '
                  'atomic notifications/audit/rollback and unknown-result retries passed; '
                  'migration003 schema and runtime grants unchanged during product actions.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))
