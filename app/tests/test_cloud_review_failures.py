"""Cloud review control flow on real isolated SQLite transactions.

These portable business-rule tests do not replace PostgreSQL fencing checks.
The adapters translate only the control/retry SQL exercised here; storage is a
fixed-generation in-memory fake and no sockets or credentials are used.
"""
from contextlib import contextmanager
from io import BytesIO
import json
import sqlite3
from types import SimpleNamespace

import pytest
from PIL import Image

from ygc import acquire_review as common, config, listing_review
from ygc.cloud_applications import CloudApplications
from ygc.cloud_content_media import decode_reference, encode_reference
from ygc.cloud_review import CloudReview, PrivatePhotoUnavailable
from ygc.cloud_storage import ObjectReference
from ygc.db.repository import Repository
from authentication_fixtures import comparison, image_bytes, transcription


class Control:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=()):
        if 'kind=ANY(%s)' in query:
            kinds, pattern = parameters
            query = query.replace('kind=ANY(%s)', 'kind IN (' + ','.join('?' for _ in kinds) + ')')
            parameters = (*kinds, pattern)
        return self.connection.execute(query.replace('%s', '?'), parameters)


class RetryConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=()):
        cursor = self.connection.execute(query.replace('%s', '?').replace(' FOR UPDATE', ''), parameters)
        return SimpleNamespace(fetchone=lambda: dict(row) if (row := cursor.fetchone()) else None)


class Photos:
    def __init__(self):
        self.objects = {}
        self.failure = None

    def put(self, data):
        reference = ObjectReference('content', 'media/' + format(len(self.objects) + 1, '032x'), 1, len(data), 'image/jpeg')
        self.objects[reference] = data
        return encode_reference(reference)

    def get(self, reference):
        if self.failure:
            raise self.failure
        if reference not in self.objects:
            raise FileNotFoundError('Fixed-generation object is missing.')
        return self.objects[reference]


@pytest.fixture
def review_setup(tmp_path):
    repo = Repository(config.DB_PATH)
    repo.init_db()
    a, b = repo.create_user('A'), repo.create_user('B')
    control_db = sqlite3.connect(tmp_path / 'paused.sqlite')
    control_db.row_factory = sqlite3.Row
    control_db.execute('CREATE TABLE paused_review_answers(revision TEXT,kind TEXT,received_at TEXT,payload TEXT,PRIMARY KEY(revision,kind))')
    control = Control(control_db)
    store = Photos()

    class Worker(CloudReview):
        enabled = True

        @contextmanager
        def transaction(self):
            with control_db:
                with repo.connect() as con:
                    yield con, control, self.enabled, {u: {'disabled': False, 'ban_status': 'normal'} for u in (a, b)}

    class Intake(CloudApplications):
        @contextmanager
        def transaction(self, actor, write=False):
            with repo.connect() as con:
                yield RetryConnection(con), actor

    worker = Worker(None, store)
    intake = Intake(None, None, store)
    counter = 0

    def prepare(kind='listing'):
        nonlocal counter
        counter += 1
        if kind == 'listing':
            draft = listing_review.start(repo, a, dict(manufacturer='Fender', serial_number=f'FIX{counter}', model='Tele', occurred_at='2020-01-01'))
            row = listing_review.submit(repo, a, draft['revision'], image_bytes(), image_bytes())
        else:
            (tmp_path / 'reference.png').write_bytes(image_bytes())
            guitar, *_ = repo.create_initial_listing_claim(a, manufacturer='Fender', model='Tele', serial_number=f'FIX{counter}', media_storage_path='reference.png', occurred_at='2020-01-01')
            draft = common.start(repo, b, guitar)
            row = common.submit(repo, b, draft['revision'], '2021-01-01', '', image_bytes(), image_bytes())
        with repo.connect() as con:
            saved = common.find(con, row['revision'])
            roles = ('closeup', 'overview') if kind == 'listing' else ('closeup', 'overview', 'reference')
            con.execute('UPDATE acquire_applications SET images=?,image_meta=?,submitted_at=? WHERE revision=?',
                        (json.dumps({role: store.put(image_bytes()) for role in roles}), json.dumps({'storage': 'gcs-content-v1'}), f'2020-01-01T00:00:{counter:02d}', saved['revision']))
        return row['revision']

    def row(revision):
        with repo.connect() as con:
            return dict(common.find(con, revision))

    def claim(revision):
        kind = row(revision)['request_kind']
        return worker.call_tool('ygc_pending_' + kind, {'remaining_revisions': [revision]})['jobs'][0]

    def observe(job):
        return worker.call_tool('ygc_' + job['request_kind'] + '_product_details', key(job) | {'observations': dict.fromkeys(('maker', 'model', 'finish'), 'overview: unknown')})

    def result(job):
        saved = row(job['revision'])
        return key(job) | dict(closeup=transcription(saved['serial'], saved['challenge']), overview=transcription(None, saved['challenge']),
                              identity=comparison()['identity'] if job['reference_available'] else None,
                              product_consistency={field: dict(status='uncertain', note='No contradiction') for field in ('maker', 'model', 'finish')})

    def remove(revision, role='closeup'):
        reference = decode_reference(json.loads(row(revision)['images'])[role])
        return reference, store.objects.pop(reference)

    def counts():
        with repo.connect() as con:
            return tuple(con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('individuals', 'claims', 'notifications'))

    yield SimpleNamespace(repo=repo, a=a, b=b, control=control, control_db=control_db, worker=worker, intake=intake,
                          store=store, prepare=prepare, row=row, claim=claim, observe=observe, result=result, remove=remove, counts=counts)
    control_db.close()


def truncated_jpeg():
    image = BytesIO()
    Image.new('RGB', (320, 240), 'white').save(image, format='JPEG')
    data = image.getvalue()[:-50]
    # Header verification alone misses this corruption.
    with Image.open(BytesIO(data)) as photo:
        photo.verify()
    return data


def key(job):
    return {field: job[field] for field in ('revision', 'lease_token')}


def paused_count(setup):
    return setup.control_db.execute('SELECT COUNT(*) FROM paused_review_answers').fetchone()[0]


@pytest.mark.parametrize('kind', ['listing', 'acquire'])
@pytest.mark.parametrize('continuation', ['submit', 'details', 'image', 'fail'])
def test_paused_failure_revokes_every_live_continuation_and_retry_rotates_lease(review_setup, kind, continuation):
    s = review_setup
    revision = s.prepare(kind)
    job = s.claim(revision)
    s.observe(job)
    payload = s.result(job)
    before = s.counts()
    s.worker.enabled = False
    assert s.worker.call_tool('ygc_fail_' + kind, key(job) | {'reason': 'Operational failure'})['paused']
    s.worker.enabled = True
    name, args = {
        'submit': ('ygc_submit_' + kind + '_review', payload),
        'details': ('ygc_' + kind + '_product_details', key(job) | {'observations': dict.fromkeys(('maker', 'model', 'finish'), 'overview: unknown')}),
        'image': ('ygc_' + kind + '_image', key(job) | {'role': 'closeup'}),
        'fail': ('ygc_fail_' + kind, key(job) | {'reason': 'Another failure'}),
    }[continuation]
    with pytest.raises(ValueError, match='lease'):
        s.worker.call_tool(name, args)
    assert s.row(revision)['status'] == 'error'
    assert s.row(revision)['lease_token'] is None
    assert paused_count(s) == 0
    assert s.counts() == before
    with pytest.raises(ValueError):
        s.worker.call_tool('ygc_submit_' + kind + '_review', payload)
    applicant = s.row(revision)['applicant_id']
    assert s.intake.retry(applicant, revision)['status'] == 'pending'
    fresh = s.claim(revision)
    assert fresh['lease_token'] != job['lease_token']
    with pytest.raises(ValueError):
        s.worker.call_tool('ygc_' + kind + '_image', key(job) | {'role': 'closeup'})
    s.observe(fresh)
    assert s.worker.call_tool('ygc_submit_' + kind + '_review', s.result(fresh))['status'] == 'accepted'


@pytest.mark.parametrize('kind', ['listing', 'acquire'])
def test_paused_success_live_retransmission_is_idempotent(review_setup, kind):
    s = review_setup
    revision = s.prepare(kind)
    job = s.claim(revision)
    s.worker.enabled = False
    s.observe(job)
    payload = s.result(job)
    s.worker.call_tool('ygc_submit_' + kind + '_review', payload)
    s.worker.enabled = True
    response = s.worker.call_tool('ygc_submit_' + kind + '_review', payload)
    assert response['status'] == 'accepted'
    before = s.counts()
    assert s.worker.call_tool('ygc_submit_' + kind + '_review', payload) == response
    assert s.counts() == before
    assert paused_count(s) == 0


@pytest.mark.parametrize('kind', ['listing', 'acquire'])
@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'truncated_jpeg', 'metadata', 'missing_role'])
def test_bad_initial_head_is_quarantined_and_next_job_leased(review_setup, kind, damage):
    s = review_setup
    bad, good = s.prepare(kind), s.prepare(kind)
    reference = decode_reference(json.loads(s.row(bad)['images'])['closeup'])
    if damage == 'missing':
        s.store.objects.pop(reference)
    elif damage == 'corrupt':
        s.store.objects[reference] = b'not an image'
    elif damage == 'truncated_jpeg':
        s.store.objects[reference] = truncated_jpeg()
    else:
        with s.repo.connect() as con:
            field, value = ('image_meta', '{}') if damage == 'metadata' else ('images', '{}')
            con.execute(f'UPDATE acquire_applications SET {field}=? WHERE revision=?', (value, bad))
    before = s.counts()
    response = s.worker.call_tool('ygc_pending_' + kind, {})
    assert [job['revision'] for job in response['jobs']] == [good]
    stopped = s.row(bad)
    assert stopped['status'] == 'error' and stopped['lease_token'] is None and stopped['attempts'] == 0
    assert s.counts() == before
    assert s.worker.call_tool('ygc_pending_' + kind, {})['jobs'] == []


@pytest.mark.parametrize('bad_kind', ['listing', 'acquire'])
@pytest.mark.parametrize('good_kind', ['listing', 'acquire'])
@pytest.mark.parametrize('damage', ['missing', 'truncated_jpeg'])
def test_bad_paused_result_does_not_block_either_queue_or_next_result(review_setup, bad_kind, good_kind, damage):
    s = review_setup
    bad, good, waiting = s.prepare(bad_kind), s.prepare(good_kind), s.prepare(good_kind)
    bad_job, good_job = s.claim(bad), s.claim(good)
    s.worker.enabled = False
    for job in (bad_job, good_job):
        s.observe(job)
        s.worker.call_tool('ygc_submit_' + job['request_kind'] + '_review', s.result(job))
    reference, _ = s.remove(bad)
    if damage == 'truncated_jpeg':
        s.store.objects[reference] = truncated_jpeg()
    s.worker.enabled = True
    response = s.worker.call_tool('ygc_pending_' + good_kind, {})
    assert [job['revision'] for job in response['jobs']] == [waiting]
    assert s.row(bad)['status'] == 'error' and s.row(bad)['claim_id'] is None and s.row(bad)['lease_token'] is None
    assert s.row(good)['status'] == 'accepted'
    assert paused_count(s) == 0
    with s.repo.connect() as con:
        assert not con.execute("SELECT 1 FROM acquire_application_events WHERE revision=? AND kind='accepted'", (bad,)).fetchone()
    assert s.worker.call_tool('ygc_fail_' + good_kind, key(response['jobs'][0]) | {'reason': 'Stop'})['status'] == 'error'


def test_missing_paused_photo_cannot_poison_live_failure_for_another_job(review_setup):
    s = review_setup
    bad, good = s.prepare(), s.prepare()
    bad_job, good_job = s.claim(bad), s.claim(good)
    s.observe(bad_job)
    s.worker.enabled = False
    s.worker.call_tool('ygc_submit_listing_review', s.result(bad_job))
    s.remove(bad)
    s.worker.enabled = True
    before = s.counts()
    assert s.worker.call_tool('ygc_fail_listing', key(good_job) | {'reason': 'Stop'})['status'] == 'error'
    assert s.row(bad)['status'] == 'error'
    assert paused_count(s) == 0 and s.counts() == before


@pytest.mark.parametrize('error', [sqlite3.IntegrityError('integrity failure'), RuntimeError('storage offline')])
def test_unknown_failures_are_not_quarantined_and_replay_transaction_rolls_back(review_setup, error):
    s = review_setup
    bad, good = s.prepare(), s.prepare()
    job = s.claim(bad)
    s.worker.enabled = False
    s.observe(job)
    s.worker.call_tool('ygc_submit_listing_review', s.result(job))
    s.store.failure = error
    s.worker.enabled = True
    before = s.counts()
    with pytest.raises(type(error)):
        s.worker.call_tool('ygc_pending_listing', {})
    assert s.row(bad)['status'] == 'processing' and s.row(bad)['product_observations'] is None
    assert s.row(good)['status'] == 'pending'
    assert paused_count(s) == 2 and s.counts() == before


def test_database_notification_failure_rolls_back_replay_and_retains_answer(review_setup):
    s = review_setup
    revision = s.prepare()
    job = s.claim(revision)
    s.worker.enabled = False
    s.observe(job)
    s.worker.call_tool('ygc_submit_listing_review', s.result(job))
    with s.repo.connect() as con:
        con.execute("CREATE TRIGGER fail_notification BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT, 'notification failure'); END")
    s.worker.enabled = True
    before = s.counts()
    with pytest.raises(sqlite3.IntegrityError, match='notification failure'):
        s.worker.call_tool('ygc_pending_listing', {})
    assert s.row(revision)['status'] == 'processing' and s.row(revision)['claim_id'] is None
    assert s.row(revision)['product_observations'] is None
    assert paused_count(s) == 2 and s.counts() == before


def test_sdk_specific_fixed_generation_failures_only(review_setup):
    pytest.importorskip('google.cloud.storage')
    from google.api_core.exceptions import Forbidden, NotFound, PreconditionFailed, ServiceUnavailable
    s = review_setup
    revision = s.prepare()
    row = s.row(revision)
    for error in (NotFound('missing'), PreconditionFailed('generation')):
        s.store.failure = error
        with pytest.raises(PrivatePhotoUnavailable):
            s.worker.photo(row, 'closeup')
    for error in (Forbidden('denied'), ServiceUnavailable('retry later')):
        s.store.failure = error
        with pytest.raises(type(error)):
            s.worker.photo(row, 'closeup')
