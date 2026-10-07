"""Admin decisions over isolated SQLite transactions and the real shared rules.

These adapters exercise business transitions, not PostgreSQL's authority/locking
boundary. postgres_admin_application_checks.py covers that boundary separately.
No model, network, credentials, or public photo publication is involved.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import sqlite3
from types import SimpleNamespace

import pytest

from ygc import acquire_review as common, config, listing_review
from ygc.cloud_admin_applications import CloudAdminApplications
from ygc.cloud_content_media import decode_reference
from ygc.cloud_owner import CloudOwner
from ygc.cloud_review import CloudReview, PrivatePhotoUnavailable
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.repository import Repository
from authentication_fixtures import comparison, image_bytes, transcription
from test_cloud_review_failures import Control, Photos, truncated_jpeg


class SharedSQLite:
    def __init__(self, con):
        self.connection = con

    def execute(self, query, parameters=()):
        return self.connection.execute(query.replace(' FOR UPDATE', '').replace(' FOR SHARE', ''), parameters)


@pytest.fixture
def admin_setup(tmp_path):
    repo = Repository(config.DB_PATH)
    repo.init_db()
    a, b, administrator = (repo.create_user(name) for name in ('Owner A', 'Applicant B', 'Admin'))
    accounts = {user: dict(id=user, app_user_id=f'account-{user}', disabled=False, ban_status='normal',
                           role='admin' if user == administrator else 'member') for user in (a, b, administrator)}
    with repo.connect() as con:
        con.execute('CREATE TABLE paused_review_answers(revision TEXT,kind TEXT,received_at TEXT,payload TEXT,PRIMARY KEY(revision,kind))')
    store = Photos()
    flags = SimpleNamespace(enabled=True)

    class Admin(CloudAdminApplications):
        @contextmanager
        def transaction(self, actor, write=False):
            account = next((item for item in accounts.values() if item['app_user_id'] == actor), None)
            if not account or account['role'] != 'admin' or account['disabled'] or account['ban_status'] != 'normal':
                raise PermissionError('Active canonical administrator required.')
            with repo.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                yield SharedSQLite(con), Control(con), flags.enabled, accounts

    class Worker(CloudReview):
        @contextmanager
        def transaction(self):
            with repo.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                yield SharedSQLite(con), Control(con), flags.enabled, accounts

    class Owner(CloudOwner):
        @contextmanager
        def transaction(self, actor, individual, *, write=False):
            account = next(item for item in accounts.values() if item['app_user_id'] == actor)
            with repo.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                yield BoundRepository(SharedSQLite(con)), account['id']

    admin = Admin(None, None, store)
    worker, owners = Worker(None, store), Owner(None, None)
    counter = 0

    def prepare(kind='listing', *, applicant=None, serial=None):
        nonlocal counter
        counter += 1
        applicant = applicant or (a if kind == 'listing' else b)
        if kind == 'listing':
            draft = listing_review.start(repo, applicant, dict(manufacturer='Fender', serial_number=serial or f'ADMIN{counter}',
                                                              model='Tele', occurred_at='2020-01-01'))
            row = listing_review.submit(repo, applicant, draft['revision'], image_bytes(), image_bytes())
        else:
            (tmp_path / 'reference.png').write_bytes(image_bytes())
            guitar, *_ = repo.create_initial_listing_claim(a, manufacturer='Fender', model='Tele', serial_number=f'ADMIN{counter}',
                media_storage_path='reference.png', occurred_at='2020-01-01')
            draft = common.start(repo, applicant, guitar)
            row = common.submit(repo, applicant, draft['revision'], '2021-01-01', 'Admin fixture', image_bytes(), image_bytes())
        with repo.connect() as con:
            if kind == 'acquire':
                from ygc.claim_revision import revision as claim_revision
                source = json.loads(common.find(con, row['revision'])['reference_source'])
                reference = con.execute('SELECT * FROM claims WHERE id=?', (source['claim_id'],)).fetchone()
                source['claim_revision'] = claim_revision(reference)
                con.execute('UPDATE acquire_applications SET reference_source=? WHERE revision=?', (json.dumps(source), row['revision']))
            roles = ('closeup', 'overview') if kind == 'listing' else ('closeup', 'overview', 'reference')
            con.execute('UPDATE acquire_applications SET images=?,image_meta=? WHERE revision=?',
                        (json.dumps({role: store.put(image_bytes()) for role in roles}),
                         json.dumps({'storage': 'gcs-content-v1'}), row['revision']))
        return row['revision']

    def row(revision):
        with repo.connect() as con:
            return dict(common.find(con, revision))

    def detail(revision):
        return admin.detail(accounts[administrator]['app_user_id'], revision)

    def decide(revision, operation, reason='Reviewed all private evidence.', version=None):
        return admin.decide(accounts[administrator]['app_user_id'], revision, operation, reason,
                            version if version is not None else detail(revision)['management_version'])

    def claim(revision):
        return worker.call_tool('ygc_pending_' + row(revision)['request_kind'], {'remaining_revisions': [revision]})['jobs'][0]

    def key(job):
        return {field: job[field] for field in ('revision', 'lease_token')}

    def observe(job):
        return worker.call_tool('ygc_' + job['request_kind'] + '_product_details', key(job) | {
            'observations': dict.fromkeys(('maker', 'model', 'finish'), 'overview: unknown')})

    def result(job):
        saved = row(job['revision'])
        return key(job) | dict(closeup=transcription(saved['serial'], saved['challenge']),
            overview=transcription(None, saved['challenge']), identity=comparison()['identity'] if job['reference_available'] else None,
            product_consistency={field: dict(status='uncertain', note='No contradiction') for field in ('maker', 'model', 'finish')})

    def snapshot():
        with repo.connect() as con:
            return {table: [tuple(row) for row in con.execute(f'SELECT * FROM {table} ORDER BY 1')]
                    for table in ('individuals', 'claims', 'claim_evidence', 'user_guitars', 'notifications',
                                  'acquire_applications', 'acquire_application_events', 'paused_review_answers')}

    return SimpleNamespace(repo=repo, a=a, b=b, administrator=administrator, actor=accounts[administrator]['app_user_id'],
        accounts=accounts, store=store, flags=flags, admin=admin, worker=worker, owners=owners, prepare=prepare, row=row,
        detail=detail, decide=decide, claim=claim, key=key, observe=observe, result=result, snapshot=snapshot)


def owner(s, guitar):
    return s.repo.get_individual(guitar)[0]['current_owner_user_id']


def verification(s, claim):
    with s.repo.connect() as con:
        return con.execute('SELECT verification_status FROM claims WHERE id=?', (claim,)).fetchone()[0]


def assert_old_lease_rejected(s, job):
    kind = job['request_kind']
    for tool, payload in (
        ('ygc_submit_' + kind + '_review', s.result(job)),
        ('ygc_' + kind + '_image', s.key(job) | {'role': 'closeup'}),
        ('ygc_' + kind + '_product_details', s.key(job) | {'observations': dict.fromkeys(('maker', 'model', 'finish'), 'old')}),
        ('ygc_fail_' + kind, s.key(job) | {'reason': 'Old reviewer'}),
    ):
        with pytest.raises(ValueError):
            s.worker.call_tool(tool, payload)


@pytest.mark.parametrize('kind', ['listing', 'acquire'])
def test_accept_exactly_once_and_never_publish_private_photos(admin_setup, kind):
    s = admin_setup
    revision = s.prepare(kind)
    before = s.snapshot()
    viewed = s.detail(revision)
    done = s.decide(revision, 'accept', version=viewed['management_version'])
    assert done['status'] == 'accepted' and done['claim_id']
    assert s.row(revision)['lease_token'] is None
    with s.repo.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == len(before['claims']) + 1
        if kind == 'listing':
            assert con.execute('SELECT COUNT(*) FROM individuals').fetchone()[0] == len(before['individuals']) + 1
            assert not con.execute('SELECT 1 FROM media_assets WHERE individual_id=?', (done['individual_id'],)).fetchone()
            assert owner(s, int(done['individual_id'])) == s.a
        events = con.execute("SELECT note FROM acquire_application_events WHERE revision=? AND kind='admin_accept'", (revision,)).fetchall()
        assert len(events) == 1
        assert s.actor in json.loads(events[0][0])['actor']
    committed = s.snapshot()
    with pytest.raises(ValueError):
        s.decide(revision, 'accept', version=viewed['management_version'])
    assert s.snapshot() == committed
    # Neither JSON endpoint may disclose fixed-generation Storage references.
    for payload in (done, s.admin.list(s.actor)):
        wire = json.dumps(payload)
        assert 'gcs-content-v1:' not in wire and '"lease_token"' not in wire


def test_acquire_owner_authority_and_admin_reversal_form_one_transition(admin_setup):
    s = admin_setup
    revision = s.prepare('acquire')
    done = s.decide(revision, 'accept')
    claim, guitar = int(done['claim_id']), int(done['individual_id'])
    assert verification(s, claim) == 'unverified' and owner(s, guitar) == s.a
    with s.repo.connect() as con:
        assert not con.execute("SELECT 1 FROM user_guitars WHERE user_id=? AND individual_id=? AND ownership_status='current_owner'", (s.b, guitar)).fetchone()
    assert s.owners.pending(s.accounts[s.b]['app_user_id'], guitar)['items'] == []
    pending = next(item for item in s.owners.pending(s.accounts[s.a]['app_user_id'], guitar)['items'] if item['id'] == str(claim))
    with pytest.raises((PermissionError, ValueError)):
        s.owners.respond(s.accounts[s.b]['app_user_id'], guitar, claim, dict(stance='positive', revision=pending['revision']))
    old_admin = s.detail(revision)['management_version']
    s.owners.respond(s.accounts[s.a]['app_user_id'], guitar, claim, dict(stance='positive', revision=pending['revision']))
    assert owner(s, guitar) == s.b
    with s.repo.connect() as con:
        owned = dict(con.execute('SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=?', (guitar,)))
        assert owned[s.a] == 'former_owner' and owned[s.b] == 'current_owner'
    assert s.owners.pending(s.accounts[s.a]['app_user_id'], guitar)['items'] == []
    assert s.owners.pending(s.accounts[s.b]['app_user_id'], guitar)['items'] == []
    with pytest.raises(ValueError):
        s.decide(revision, 'reject', version=old_admin)
    rejected = s.decide(revision, 'reject')
    assert int(rejected['claim_id']) == claim and verification(s, claim) == 'negative'
    assert owner(s, guitar) == s.a
    count = len(s.snapshot()['claims'])
    accepted = s.decide(revision, 'accept')
    assert int(accepted['claim_id']) == claim and len(s.snapshot()['claims']) == count
    assert verification(s, claim) == 'unverified' and owner(s, guitar) == s.a


@pytest.mark.parametrize('kind', ['listing', 'acquire'])
@pytest.mark.parametrize('operation', ['accept', 'reject', 'retry', 'cancel'])
def test_off_allows_manual_actions_and_fences_retained_old_answers(admin_setup, kind, operation):
    s = admin_setup
    revision = s.prepare(kind)
    job = s.claim(revision)
    s.flags.enabled = False
    s.observe(job)
    assert s.worker.call_tool('ygc_submit_' + kind + '_review', s.result(job))['applied'] is False
    previous = s.detail(revision)['management_version']
    outcome = s.decide(revision, operation, version=previous)
    assert outcome['status'] == dict(accept='accepted', reject='rejected', retry='pending', cancel='cancelled')[operation]
    assert s.row(revision)['lease_token'] is None
    before = s.snapshot()
    assert s.worker.call_tool('ygc_pending_' + kind, {})['jobs'] == []
    assert s.snapshot() == before
    s.flags.enabled = True
    assert_old_lease_rejected(s, job)
    if operation == 'retry':
        fresh = s.claim(revision)
        assert fresh['lease_token'] != job['lease_token']
        assert s.row(revision)['attempts'] == 1
    else:
        assert s.worker.call_tool('ygc_pending_' + kind, {'remaining_revisions': [revision]})['jobs'] == []
        assert s.row(revision)['status'] == outcome['status']
    with s.repo.connect() as con:
        assert not con.execute('SELECT 1 FROM paused_review_answers WHERE revision=?', (revision,)).fetchone()
        assert con.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == len(before['claims'])


@pytest.mark.parametrize('kind', ['listing', 'acquire'])
def test_notification_failure_rolls_back_whole_manual_decision(admin_setup, kind):
    s = admin_setup
    revision = s.prepare(kind)
    job = s.claim(revision)
    s.flags.enabled = False
    s.observe(job)
    s.worker.call_tool('ygc_submit_' + kind + '_review', s.result(job))
    version = s.detail(revision)['management_version']
    with s.repo.connect() as con:
        con.execute("CREATE TRIGGER fail_admin_notice BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT, 'notification storage failed'); END")
    before = s.snapshot()
    with pytest.raises(sqlite3.IntegrityError, match='notification storage failed'):
        s.decide(revision, 'accept', version=version)
    assert s.snapshot() == before
    with s.repo.connect() as con:
        con.execute('DROP TRIGGER fail_admin_notice')
    assert s.decide(revision, 'accept', version=version)['status'] == 'accepted'


@pytest.mark.parametrize('operation', ['accept', 'retry'])
@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'truncated_jpeg', 'metadata', 'missing_role'])
def test_private_photo_damage_blocks_accept_or_retry_without_side_effects(admin_setup, operation, damage):
    s = admin_setup
    revision = s.prepare('acquire')
    ref = decode_reference(json.loads(s.row(revision)['images'])['reference'])
    if damage == 'missing':
        s.store.objects.pop(ref)
    elif damage in ('corrupt', 'truncated_jpeg'):
        s.store.objects[ref] = b'not an image' if damage == 'corrupt' else truncated_jpeg()
    else:
        with s.repo.connect() as con:
            field, value = ('image_meta', '{}') if damage == 'metadata' else ('images', '{}')
            con.execute(f'UPDATE acquire_applications SET {field}=? WHERE revision=?', (value, revision))
    before = s.snapshot()
    version = next(item['management_version'] for item in s.admin.list(s.actor)['items'] if item['revision'] == revision)
    with pytest.raises(PrivatePhotoUnavailable):
        s.decide(revision, operation, version=version)
    assert s.snapshot() == before


@pytest.mark.parametrize('damage', ['disabled', 'banned', 'serial', 'product', 'reference_claim', 'reference_revision'])
@pytest.mark.parametrize('operation', ['accept', 'retry'])
def test_changed_applicant_or_acquire_evidence_blocks_manual_acceptance(admin_setup, damage, operation):
    s = admin_setup
    revision = s.prepare('acquire')
    row = s.row(revision)
    if damage == 'disabled':
        s.accounts[s.b]['disabled'] = True
    elif damage == 'banned':
        s.accounts[s.b]['ban_status'] = 'ban'
    else:
        with s.repo.connect() as con:
            if damage in ('serial', 'product'):
                column = 'serial_number' if damage == 'serial' else 'model'
                con.execute(f'UPDATE individuals SET {column}=? WHERE id=?', ('CHANGED', row['individual_id']))
            else:
                claim = json.loads(row['reference_source'])['claim_id']
                if damage == 'reference_claim':
                    con.execute("UPDATE claims SET verification_status='negative' WHERE id=?", (claim,))
                else:
                    con.execute("UPDATE claims SET body='Edited since submission',updated_at='changed-fixture-revision' WHERE id=?", (claim,))
    before = s.snapshot()
    with pytest.raises(ValueError):
        s.decide(revision, operation)
    assert s.snapshot() == before


def test_concurrent_duplicate_listing_creates_one_individual(admin_setup):
    s = admin_setup
    first = s.prepare('listing', applicant=s.a, serial='ADMIN-DUPLICATE')
    second = s.prepare('listing', applicant=s.b, serial='ADMIN-DUPLICATE')
    versions = {revision: s.detail(revision)['management_version'] for revision in (first, second)}

    def accept(revision):
        try:
            return s.decide(revision, 'accept', version=versions[revision])['status']
        except ValueError:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(accept, (first, second))) == ['accepted', 'conflict']
    with s.repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM individuals WHERE normalized_serial='ADMIN-DUPLICATE'").fetchone()[0] == 1
        assert con.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == 1


@pytest.mark.parametrize('operation', ['positive', 'negative', 'unverified', 'delete', ''])
def test_application_management_cannot_force_claim_verification(admin_setup, operation):
    s = admin_setup
    revision = s.prepare('acquire')
    s.decide(revision, 'accept')
    before = s.snapshot()
    with pytest.raises(ValueError):
        s.decide(revision, operation)
    assert s.snapshot() == before


@pytest.mark.parametrize('reason', [None, True, 4, [], {}, '', '  ', 'x' * 2001])
def test_every_manual_action_needs_bounded_nonempty_reason(admin_setup, reason):
    s = admin_setup
    revision = s.prepare()
    before = s.snapshot()
    with pytest.raises(ValueError):
        s.decide(revision, 'accept', reason=reason)
    assert s.snapshot() == before


def test_list_filters_literal_search_and_keyset_pagination(admin_setup):
    s = admin_setup
    revisions = [s.prepare('listing', serial=serial) for serial in ('PAGE%_ONE', 'PAGE_TWO', 'PAGE_THREE')]
    acquire = s.prepare('acquire')
    s.decide(revisions[1], 'reject')
    first = s.admin.list(s.actor, kind='listing', limit=2)
    assert int(first['total']) == 3 and len(first['items']) == 2 and first['next_after']
    second = s.admin.list(s.actor, kind='listing', limit=2, after=first['next_after'])
    assert int(second['total']) == 3 and second['next_after'] is None
    assert {row['revision'] for row in first['items'] + second['items']} == set(revisions)
    assert [row['revision'] for row in s.admin.list(s.actor, q='%_')['items']] == [revisions[0]]
    assert [row['revision'] for row in s.admin.list(s.actor, status='rejected')['items']] == [revisions[1]]
    assert [row['revision'] for row in s.admin.list(s.actor, kind='acquire', q='Applicant B')['items']] == [acquire]
    assert s.admin.list(s.actor, q='no such serial')['items'] == []


def test_reads_do_not_expire_drafts_or_add_events(admin_setup):
    s = admin_setup
    draft = listing_review.start(s.repo, s.a, dict(manufacturer='Fender', serial_number='EXPIRED-READ', model='Tele', occurred_at='2020-01-01'))
    with s.repo.connect() as con:
        con.execute('UPDATE acquire_applications SET expires_at=0 WHERE revision=?', (draft['revision'],))
    before = s.snapshot()
    detail = s.detail(draft['revision'])
    assert detail['status'] == 'expired' and detail['admin_actions'] == []
    assert s.admin.list(s.actor, status='expired')['items'][0]['revision'] == draft['revision']
    assert s.snapshot() == before


def test_new_observations_without_event_invalidate_old_admin_view(admin_setup):
    s = admin_setup
    revision = s.prepare()
    job = s.claim(revision)
    old = s.detail(revision)['management_version']
    s.observe(job)
    assert old != s.detail(revision)['management_version']
    before = s.snapshot()
    with pytest.raises(ValueError):
        s.decide(revision, 'reject', version=old)
    assert s.snapshot() == before


@pytest.mark.parametrize('kind', ['listing', 'acquire'])
def test_manual_reversal_keeps_original_ai_diagnostic_and_audit_history(admin_setup, kind):
    s = admin_setup
    revision = s.prepare(kind)
    job = s.claim(revision)
    s.observe(job)
    s.worker.call_tool('ygc_submit_' + kind + '_review', s.result(job))
    original = s.row(revision)
    original_events = s.detail(revision)['events']
    declined = s.decide(revision, 'reject', reason='Human evidence changes the image decision.')
    row = s.row(revision)
    assert row['status'] == 'rejected' and int(declined['claim_id']) == original['claim_id']
    assert {key: row[key] for key in ('received', 'result', 'report')} == {key: original[key] for key in ('received', 'result', 'report')}
    assert declined['events'][:len(original_events)] == original_events
    assert declined['admin_review']['reason'] == 'Human evidence changes the image decision.'
    assert_old_lease_rejected(s, job)


def test_listing_rejection_rebuilds_snapshot_and_reaccept_reuses_claim(admin_setup):
    s = admin_setup
    revision = s.prepare()
    accepted = s.decide(revision, 'accept')
    claim, guitar = int(accepted['claim_id']), int(accepted['individual_id'])
    before = len(s.snapshot()['claims'])
    rejected = s.decide(revision, 'reject')
    assert rejected['verification_status'] == 'negative' and owner(s, guitar) is None
    restored = s.decide(revision, 'accept')
    assert int(restored['claim_id']) == claim and restored['verification_status'] == 'positive'
    assert owner(s, guitar) == s.a and len(s.snapshot()['claims']) == before


def test_acquire_with_no_current_user_owner_uses_existing_positive_rule(admin_setup):
    s = admin_setup
    revision = s.prepare('acquire')
    guitar = s.row(revision)['individual_id']
    s.repo.create_ownership_claim(s.a, guitar, ownership_kind='release', occurred_at='2020-02-01')
    assert owner(s, guitar) is None
    result = s.decide(revision, 'accept')
    assert result['verification_status'] == 'positive' and owner(s, guitar) == s.b


@pytest.mark.parametrize('operation', ['accept', 'reject', 'retry', 'cancel'])
def test_old_answers_left_after_content_commit_are_harmless(admin_setup, operation):
    s = admin_setup
    revision = s.prepare()
    job = s.claim(revision)
    s.flags.enabled = False
    s.observe(job)
    s.worker.call_tool('ygc_submit_listing_review', s.result(job))
    with s.repo.connect() as con:
        retained = [tuple(row) for row in con.execute('SELECT * FROM paused_review_answers WHERE revision=?', (revision,))]
    s.decide(revision, operation)
    # Model an interrupted Operations commit after Chronicle committed. Safety
    # must come from the revoked lease, independently of answer deletion.
    with s.repo.connect() as con:
        con.executemany('INSERT INTO paused_review_answers VALUES(?,?,?,?)', retained)
    s.flags.enabled = True
    before = s.snapshot()
    assert s.worker.call_tool('ygc_pending_listing', {'remaining_revisions': []})['jobs'] == []
    after = s.snapshot()
    assert after['paused_review_answers'] == []
    assert {key: value for key, value in after.items() if key != 'paused_review_answers'} == {
        key: value for key, value in before.items() if key != 'paused_review_answers'}
    assert_old_lease_rejected(s, job)


@pytest.mark.parametrize('operation', ['reject', 'cancel'])
@pytest.mark.parametrize('metadata', ['{}', '{broken json', '[]', 'null', '"wrong type"'])
def test_invalid_photo_metadata_remains_inspectable_and_stoppable(admin_setup, operation, metadata):
    s = admin_setup
    revision = s.prepare()
    with s.repo.connect() as con:
        con.execute('UPDATE acquire_applications SET image_meta=? WHERE revision=?', (metadata, revision))
    view = s.detail(revision)
    assert view['photos_unavailable'] and view['photos'] == [] and view['events']
    before = s.snapshot()
    for blocked in ('accept', 'retry'):
        with pytest.raises(PrivatePhotoUnavailable):
            s.decide(revision, blocked)
        assert s.snapshot() == before
    assert s.decide(revision, operation)['status'] == {'reject': 'rejected', 'cancel': 'cancelled'}[operation]


@pytest.mark.parametrize('kind', ['listing'])
@pytest.mark.parametrize('operation', ['accept', 'retry'])
def test_expired_draft_does_not_block_submitted_application(admin_setup, kind, operation):
    s = admin_setup
    revision = s.prepare(kind)
    # Cloud reads intentionally leave expired drafts physically unchanged. Model
    # an earlier draft retained beside the newer, valid submitted application.
    expired = dict(s.row(revision), revision='0' * 32, status='draft', expires_at=0, images=None,
                   submitted_at=None, created_at='2019-01-01T00:00:00+00:00')
    with s.repo.connect() as con:
        columns = ','.join(expired)
        con.execute(f"INSERT INTO acquire_applications({columns}) VALUES ({','.join('?' for _ in expired)})", tuple(expired.values()))
    before = s.row(expired['revision'])
    result = s.decide(revision, operation)
    assert result['status'] == {'accept': 'accepted', 'retry': 'pending'}[operation]
    assert s.row(expired['revision']) == before
    with s.repo.connect() as con:
        assert not con.execute('SELECT 1 FROM acquire_application_events WHERE revision=?', (expired['revision'],)).fetchone()


def test_retry_preserves_partial_independent_observations_and_error(admin_setup):
    s = admin_setup
    revision = s.prepare('listing')
    job = s.claim(revision)
    s.observe(job)
    observed = json.loads(s.row(revision)['product_observations'])
    s.worker.call_tool('ygc_fail_listing', s.key(job) | {'reason': 'Image processing interrupted'})
    done = s.decide(revision, 'retry')
    assert s.row(revision)['product_observations'] is None
    note = json.loads(next(e['note'] for e in done['events'] if e['kind'] == 'admin_retry'))
    assert note['previous_review']['product_observations'] == observed
    assert note['previous_review']['error'] == 'Image processing interrupted'


@pytest.mark.parametrize('operation', ['accept', 'reject', 'cancel', 'retry'])
def test_admin_retains_off_answer_diagnostics_without_worker_authority(admin_setup, operation):
    s = admin_setup
    revision = s.prepare('listing')
    job = s.claim(revision)
    s.flags.enabled = False
    observed = dict.fromkeys(('maker', 'model', 'finish'), 'overview: independent observation')
    s.worker.call_tool('ygc_listing_product_details', s.key(job) | {'observations': observed})
    s.worker.call_tool('ygc_submit_listing_review', s.result(job))
    done = s.decide(revision, operation)
    note = json.loads(next(e['note'] for e in done['events'] if e['kind'] == 'admin_' + operation))
    retained = note['review_context']['retained_answers']
    assert len(retained) == 2
    assert next(e for e in retained if e['kind'].endswith('product_details'))['payload']['observations'] == observed
    assert job['lease_token'] not in json.dumps(note)
    with s.repo.connect() as con:
        stored = con.execute('SELECT note FROM acquire_application_events WHERE revision=? AND kind=?', (revision, 'admin_' + operation)).fetchone()[0]
        assert job['lease_token'] not in stored
        assert not con.execute('SELECT 1 FROM paused_review_answers WHERE revision=?', (revision,)).fetchone()


def test_retry_history_keeps_original_report_but_redacts_private_report_locators(admin_setup):
    s = admin_setup
    revision = s.prepare('listing')
    path = json.loads(s.row(revision)['images'])['closeup']
    report = 'Original partial report: ' + json.dumps({'path': path, 'observed': 'uncertain'})
    with s.repo.connect() as con:
        con.execute("UPDATE acquire_applications SET status='error',report=? WHERE revision=?", (report, revision))
    done = s.decide(revision, 'retry')
    assert path not in json.dumps(done)
    note = json.loads(next(e['note'] for e in done['events'] if e['kind'] == 'admin_retry'))
    assert '[private reference]' in note['previous_review']['report']
    assert 'uncertain' in note['previous_review']['report']
    with s.repo.connect() as con:
        stored = json.loads(con.execute("SELECT note FROM acquire_application_events WHERE revision=? AND kind='admin_retry'", (revision,)).fetchone()[0])
        assert stored['previous_review']['report'] == report


def test_new_acquire_after_draft_expiry_releases_the_unique_active_slot(admin_setup):
    from ygc.cloud_applications import CloudApplications
    from ygc.db.postgres_queries import SharedRow
    s = admin_setup
    revision = s.prepare('acquire')
    guitar = s.row(revision)['individual_id']
    with s.repo.connect() as con:
        con.execute("UPDATE acquire_applications SET status='draft',expires_at=0 WHERE revision=?", (revision,))

    class IntakeConnection:
        def __init__(self, con):
            self.con = con

        def execute(self, query, parameters=()):
            if 'status=ANY(%s)' in query:
                values = parameters[-1] if len(parameters) == 3 else parameters[1]
                query = query.replace('status=ANY(%s)', 'status IN (' + ','.join('%s' for _ in values) + ')')
                parameters = (*parameters[:2], *values) if len(parameters) == 3 else (parameters[0], *values, *parameters[2:])
            cursor = self.con.execute(query.replace('%s', '?').replace(' FOR UPDATE', ''), parameters)
            class Rows:
                def fetchone(self):
                    row = cursor.fetchone()
                    return SharedRow(row) if row is not None else None

                def __iter__(self):
                    return (SharedRow(row) for row in cursor)
            return Rows()

    class Intake(CloudApplications):
        @contextmanager
        def transaction(self, actor, write=False):
            with s.repo.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                yield IntakeConnection(con), s.b, {'mode': 'normal'}

    intake = Intake(None, None, s.store)
    created = intake.start('fixture', {'kind': 'acquire', 'individual_id': str(guitar)})
    assert created['revision'] != revision and created['status'] == 'draft'
    assert s.row(revision)['status'] == 'expired'
    with s.repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM acquire_application_events WHERE revision=? AND kind='expired'", (revision,)).fetchone()[0] == 1
    assert intake.start('fixture', {'kind': 'acquire', 'individual_id': str(guitar)})['revision'] == created['revision']
