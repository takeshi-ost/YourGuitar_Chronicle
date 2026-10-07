"""Admin review invariants on disposable local PostgreSQL databases only.

Invoked by run_postgres_checks.py. No cloud host, model, live account, or remote
Storage is involved. The portable companion tests do not substitute for these
canonical account, projection, mutex, commit-order and concurrency checks.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import uuid

import psycopg
from psycopg import errors, sql

from ygc.admin_bootstrap_job import grant_first_admin
from ygc.cloud_admin_applications import CloudAdminApplications
from ygc.cloud_applications import CloudApplications, references
from ygc.cloud_content_media import decode_reference, MediaConflict
from ygc.cloud_owner import CloudOwner
from ygc.cloud_review import CloudReview, PrivatePhotoUnavailable
from ygc.db.postgres import PostgresSettings, bootstrap, migrate, connect
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations
from authentication_fixtures import transcription, comparison
from test_cloud_avatar import Storage, png


def rejected(error, operation):
    try:
        operation()
    except error:
        return
    raise AssertionError('Expected ' + error.__name__)


def run(port):
    prefix = 'ygctest_admin_review_' + uuid.uuid4().hex[:10] + '_'
    role = prefix + 'app'
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port, prefix)
    app = replace(owner, user=role)
    databases = []
    with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='postgres',
                         password='ygc-tests-only', autocommit=True) as system:
        try:
            system.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal('ygc-tests-only')))
            for target in ('accounts', 'chronicle', 'operations'):
                name = owner.database(target)
                system.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                databases.append(name)
                bootstrap(owner, target, role)
                migrate(owner, target, role)
            accounts, operations = PostgresAccounts(app), PostgresOperations(app)
            a = accounts.ensure_identity(issuer='admin-review-fixture', subject='admin', display_name='Admin owner')
            b = accounts.ensure_identity(issuer='admin-review-fixture', subject='applicant', display_name='Applicant')
            aid, bid = a['app_user_id'], b['app_user_id']
            assert grant_first_admin(app, aid, 'local-test-operator')
            accounts.drain_projection()
            operations.set_mode(aid, mode='normal', message='', version=operations.details(aid)['version'])
            checks(app, owner, accounts, operations, Storage(), a, b)
            print('PostgreSQL Admin applications: canonical Admin fences, projection/mutex locks, OFF manual actions, retained-answer invalidation, Owner authority, Snapshot reversal, notification rollback, private photos and concurrent exactly-once Listing passed.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))


def checks(app, db_owner, accounts, operations, store, a, b):
    aid, bid = a['app_user_id'], b['app_user_id']
    admin = CloudAdminApplications(app, operations, store)
    intake, worker, owners = CloudApplications(app, operations, store), CloudReview(app, store), CloudOwner(app, operations)

    def enabled(value):
        current = operations.review_status(aid)['enabled']
        if current != value:
            operations.set_review(aid, enabled=value, expected_enabled=current)

    def submit(actor, serial=None, guitar=None):
        payload = dict(manufacturer='Fender', serial_number=serial, model='Tele', finish='', year='', occurred_at='2020-01-01', body='Admin review fixture')
        request = dict(kind='listing', payload=payload) if guitar is None else dict(kind='acquire', individual_id=str(guitar))
        row = intake.start(actor, request)
        for role in ('closeup', 'overview'):
            intake.upload(actor, row['revision'], role, png(), 'image/png')
        return intake.submit(actor, row['revision'], dict(acquisition_date='2020-01-01' if guitar is None else '2021-01-01', body='Admin review fixture'))

    def detail(row):
        return admin.detail(aid, row['revision'])

    def decide(row, operation, version=None):
        return admin.decide(aid, row['revision'], operation, 'Examined private evidence.', version or detail(row)['management_version'])

    def record(row):
        with connect(app, 'chronicle') as con:
            return con.execute('SELECT * FROM acquire_applications WHERE revision=%s', (row['revision'],)).fetchone()

    def current_owner(guitar):
        with connect(app, 'chronicle') as con:
            return con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (guitar,)).fetchone()['current_owner_user_id']

    def snapshot():
        with connect(app, 'chronicle') as con:
            tables = {table: list(con.execute('SELECT * FROM ' + table + ' ORDER BY 1')) for table in
                ('acquire_applications', 'acquire_application_events', 'claims', 'claim_evidence', 'individuals', 'notifications', 'user_guitars')}
        with connect(app, 'operations') as con:
            tables['paused_review_answers'] = list(con.execute('SELECT * FROM paused_review_answers ORDER BY revision,kind'))
        return tables

    def claim(row):
        return worker.call_tool('ygc_pending_' + row['kind'], {'remaining_revisions': [row['revision']]})['jobs'][0]

    def key(job):
        return {field: job[field] for field in ('revision', 'lease_token')}

    def observations(job):
        return key(job) | {'observations': dict.fromkeys(('maker', 'model', 'finish'), 'overview: unknown fixture feature')}

    def answer(row, job):
        return key(job) | dict(closeup=transcription(row['serial'], row['challenge']), overview=transcription(None, row['challenge']),
            identity=comparison()['identity'] if job['reference_available'] else None,
            product_consistency={field: dict(status='uncertain', note='No contradiction') for field in ('maker', 'model', 'finish')})

    listing = submit(aid, 'ADMIN-PG-001')
    revision = listing['revision']
    version = detail(listing)['management_version']
    operations_for = lambda actor: (
        lambda: admin.list(actor), lambda: admin.detail(actor, revision),
        lambda: admin.image(actor, revision, 'closeup'),
        lambda: admin.decide(actor, revision, 'accept', 'Evidence checked.', version))
    for actor in (bid, 'unknown-canonical-account', None):
        for action in operations_for(actor):
            rejected(PermissionError, action)
    # Canonical identity always wins even when the projected user still exists.
    for column, value, restored in (('role', 'member', 'admin'), ('disabled', 1, 0), ('ban_status', 'ban', 'normal')):
        with connect(app, 'accounts') as con:
            con.execute(sql.SQL('UPDATE account_records SET {}=%s WHERE app_user_id=%s').format(sql.Identifier(column)), (value, aid))
        accounts.drain_projection()
        try:
            for action in operations_for(aid):
                rejected(PermissionError, action)
        finally:
            with connect(app, 'accounts') as con:
                con.execute(sql.SQL('UPDATE account_records SET {}=%s WHERE app_user_id=%s').format(sql.Identifier(column)), (restored, aid))
            accounts.drain_projection()
    # Refuse stale or unknown Chronicle projection; never silently use it.
    accounts.update_profile(bid, {'bio': 'Projection intentionally delayed'})
    rejected(ValueError, lambda: decide(listing, 'accept', version))
    accounts.drain_projection()
    with connect(app, 'chronicle') as con:
        con.execute("INSERT INTO users(id,display_name,created_at,updated_at,app_user_id) VALUES(99999,'unknown','now','now','unknown-projection')")
    try:
        rejected(ValueError, lambda: admin.list(aid))
    finally:
        with connect(app, 'chronicle') as con:
            con.execute('DELETE FROM users WHERE id=99999')
    # All page reads and writes honor the same maintenance/restore mutex.
    with connect(app, 'operations') as con:
        con.execute('SELECT pg_advisory_xact_lock(79432190)')
        for action in operations_for(aid):
            rejected(MediaConflict, action)
    # Holding the Admin context keeps role, participants and projection
    # serialized through the content transaction, not just at the first check.
    with admin.transaction(aid, write=True):
        def mutate_account():
            with connect(app, 'accounts') as con:
                con.execute('SET statement_timeout=100')
                con.execute("UPDATE account_records SET role='member' WHERE app_user_id=%s", (aid,))
        rejected(errors.QueryCanceled, mutate_account)
        with connect(app, 'chronicle') as con:
            assert not con.execute('SELECT pg_try_advisory_xact_lock(79432002) AS locked').fetchone()['locked']
        with connect(app, 'operations') as con:
            assert not con.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']
    # A review switch is a worker gate, never a blanket block on Admin outcomes.
    enabled(False)
    assert worker.call_tool('ygc_pending_listing', {})['jobs'] == []
    accepted = decide(listing, 'accept', version)
    assert accepted['status'] == 'accepted'
    guitar = int(accepted['individual_id'])
    assert current_owner(guitar) == a['id']
    before = snapshot()
    rejected(ValueError, lambda: decide(listing, 'accept', version))
    assert snapshot() == before
    with connect(app, 'chronicle') as con:
        assert not con.execute('SELECT 1 FROM media_assets WHERE individual_id=%s', (guitar,)).fetchone()
    assert admin.image(aid, revision, 'overview')
    assert 'gcs-content-v1:' not in json.dumps(detail(listing))
    assert 'lease_token' not in json.dumps(admin.list(aid))

    expired = intake.start(bid, dict(kind='acquire', individual_id=str(guitar)))
    with connect(app, 'chronicle') as con:
        con.execute('UPDATE acquire_applications SET expires_at=0 WHERE revision=%s', (expired['revision'],))
    assert intake.list(bid)['items'][0]['status'] == 'expired'
    assert record(expired)['status'] == 'draft'  # GET does not mutate expiry.
    acquire = submit(bid, guitar=guitar)
    assert acquire['revision'] != expired['revision'] and record(expired)['status'] == 'expired'

    acquired = decide(acquire, 'accept')
    claim_id = int(acquired['claim_id'])
    assert acquired['verification_status'] == 'unverified' and current_owner(guitar) == a['id']
    pending = next(row for row in owners.pending(aid, guitar)['items'] if row['id'] == str(claim_id))
    assert owners.pending(bid, guitar)['items'] == []
    rejected(ValueError, lambda: owners.respond(bid, guitar, claim_id, dict(stance='positive', revision=pending['revision'])))
    stale = detail(acquire)['management_version']
    owners.respond(aid, guitar, claim_id, dict(stance='positive', revision=pending['revision']))
    assert current_owner(guitar) == b['id']
    assert owners.pending(aid, guitar)['items'] == [] and owners.pending(bid, guitar)['items'] == []
    with connect(app, 'chronicle') as con:
        statuses = {row['user_id']: row['ownership_status'] for row in con.execute('SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=%s', (guitar,))}
        assert statuses[a['id']] == 'former_owner' and statuses[b['id']] == 'current_owner'
    rejected(ValueError, lambda: decide(acquire, 'reject', stale))
    declined = decide(acquire, 'reject')
    assert declined['verification_status'] == 'negative' and current_owner(guitar) == a['id']
    visible = next(item for item in intake.list(bid)['items'] if item['revision'] == acquire['revision'])
    assert visible['admin_review']['operation'] == 'reject' and visible['admin_review']['reason'] == 'Examined private evidence.'
    reaccepted = decide(acquire, 'accept')
    assert int(reaccepted['claim_id']) == claim_id and reaccepted['verification_status'] == 'unverified'
    assert current_owner(guitar) == a['id']

    # Every reasoned manual outcome revokes authority of an already running
    # reviewer, including answers received and held while Review was OFF.
    for operation in ('accept', 'reject', 'cancel', 'retry'):
        queued = submit(bid, 'ADMIN-PG-OFF-' + operation.upper())
        enabled(True)
        job = claim(queued)
        enabled(False)
        stale = detail(queued)['management_version']
        worker.call_tool('ygc_listing_product_details', observations(job))
        worker.call_tool('ygc_submit_listing_review', answer(queued, job))
        rejected(ValueError, lambda: decide(queued, operation, stale))
        changed = decide(queued, operation)
        assert changed['status'] == dict(accept='accepted', reject='rejected', cancel='cancelled', retry='pending')[operation]
        assert record(queued)['lease_token'] is None
        visible = next(item for item in intake.list(bid)['items'] if item['revision'] == queued['revision'])
        if operation == 'retry':
            assert visible['admin_review'] is None
        elif operation in ('accept', 'reject'):
            assert visible['admin_review']['operation'] == operation and visible['admin_review']['reason'] == 'Examined private evidence.'
        assert worker.call_tool('ygc_pending_listing', {})['jobs'] == []
        enabled(True)
        rejected(ValueError, lambda: worker.call_tool('ygc_submit_listing_review', answer(queued, job)))
        rejected(ValueError, lambda: worker.call_tool('ygc_listing_image', key(job) | {'role': 'closeup'}))
        rejected(ValueError, lambda: worker.call_tool('ygc_listing_product_details', observations(job)))
        rejected(ValueError, lambda: worker.call_tool('ygc_fail_listing', key(job) | {'reason': 'stale reviewer'}))
        if operation == 'retry':
            fresh = claim(queued)
            assert fresh['lease_token'] != job['lease_token']
            decide(queued, 'cancel')
        else:
            assert worker.call_tool('ygc_pending_listing', {'remaining_revisions': [queued['revision']]})['jobs'] == []
        with connect(app, 'operations') as con:
            assert not con.execute('SELECT 1 FROM paused_review_answers WHERE revision=%s', (queued['revision'],)).fetchone()

    # Chronicle must completely roll back if the final applicant notice fails;
    # separately retained answers must survive with their original lease.
    queued = submit(bid, 'ADMIN-PG-ROLLBACK')
    job = claim(queued)
    enabled(False)
    worker.call_tool('ygc_listing_product_details', observations(job))
    worker.call_tool('ygc_submit_listing_review', answer(queued, job))
    before, version = snapshot(), detail(queued)['management_version']
    with connect(db_owner, 'chronicle') as con:
        con.execute(sql.SQL('REVOKE INSERT ON notifications FROM {}').format(sql.Identifier(app.user)))
    try:
        rejected(errors.InsufficientPrivilege, lambda: decide(queued, 'accept', version))
        assert snapshot() == before
    finally:
        with connect(db_owner, 'chronicle') as con:
            con.execute(sql.SQL('GRANT INSERT ON notifications TO {}').format(sql.Identifier(app.user)))
    assert decide(queued, 'accept', version)['status'] == 'accepted'

    damaged = submit(bid, 'ADMIN-PG-PHOTO')
    ref = decode_reference(references(record(damaged))['closeup'])
    content = store.objects.pop(ref)
    before = snapshot()
    for operation in ('accept', 'retry'):
        rejected(PrivatePhotoUnavailable, lambda: decide(damaged, operation))
        assert snapshot() == before
    store.objects[ref] = content
    decide(damaged, 'cancel')

    # A concurrent attempt may lose the try-lock. Once the winner commits, the
    # loser still cannot create an Individual for the same Maker/Serial.
    left, right = submit(aid, 'ADMIN-PG-DUP'), submit(bid, 'ADMIN-PG-DUP')
    versions = {row['revision']: detail(row)['management_version'] for row in (left, right)}
    def accept_duplicate(row):
        try:
            return decide(row, 'accept', versions[row['revision']])['status']
        except (ValueError, MediaConflict):
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(accept_duplicate, (left, right))) == ['accepted', 'conflict']
    loser = next(row for row in (left, right) if record(row)['status'] != 'accepted')
    rejected(ValueError, lambda: decide(loser, 'accept'))
    with connect(app, 'chronicle') as con:
        assert con.execute("SELECT COUNT(*) AS n FROM individuals WHERE normalized_serial='ADMIN-PG-DUP'").fetchone()['n'] == 1
        assert con.execute("SELECT COUNT(*) AS n FROM acquire_applications WHERE serial='ADMIN-PG-DUP' AND status='accepted'").fetchone()['n'] == 1
