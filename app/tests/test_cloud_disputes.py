"""Synthetic private dispute service/DTO tests; no reviewer or live data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import sqlite3
from unittest.mock import Mock

import pytest

from authentication_fixtures import image_bytes
from dispute_storage_fixtures import MemoryOriginalStorage, add_originals_table
from ygc import disputes
from ygc.claim_revision import ClaimConflict
from ygc.cloud_disputes import CloudDisputes, DisputeConnection
from ygc.cloud_dispute_dto import (acknowledgment_payload, submission_payload,
    publication_payload, decision_payload, result_projection, request_projection)
from ygc.cloud_guitars import GuitarMissing
from ygc.db.postgres_operations import ServiceRestricted
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.repository import Repository

BIG = 2**53 + 19
PDF = b'%PDF-1.4 synthetic private evidence\n%%EOF'
OPEN = dict(case_id=None, version=None, round_number=None, explanation='How I acquired this guitar.', summary='Purchased in 2025.')


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    repo = Repository(tmp_path / 'private-disputes.db')
    repo.init_db()
    with repo.connect() as con:
        con.execute('ALTER TABLE users ADD COLUMN app_user_id TEXT')
        add_originals_table(con)
        for table in ('users', 'individuals', 'claims', 'ownership_disputes', 'ownership_dispute_rounds',
                      'ownership_dispute_evidence', 'ownership_dispute_events'):
            con.execute('INSERT OR REPLACE INTO sqlite_sequence(name,seq) VALUES (?,?)', (table, BIG))
    owner, applicant, competitor, admin, outsider = (repo.create_user(n) for n in
        ('Original owner', 'Applicant', 'Competitor', 'Admin', 'Outsider'))
    individual, *_ = repo.create_initial_listing_claim(owner, manufacturer='Fixture', model='Dispute',
        serial_number='PRIVATE-001', media_storage_path='private/fixture.jpg', occurred_at='2020-01-01')
    service = CloudDisputes(None, None, MemoryOriginalStorage())
    state = {'mode': 'normal', 'admin': admin, 'trace': []}

    @contextmanager
    def transaction(actor, *, claim=None, case=None, evidence=None, admin=False, write=False, listing=None):
        with repo.connect() as con:
            con.set_trace_callback(state['trace'].append)
            if write:
                con.execute('BEGIN IMMEDIATE')
            if not admin and (state['mode'] == 'offline' or (write and state['mode'] == 'read_only')):
                raise ServiceRestricted()
            disputes.available(con, actor)
            if admin and actor != state['admin']:
                raise PermissionError()
            if listing is None:
                service._target(con, actor, claim=claim, case=case, evidence=evidence, admin=admin)
            yield BoundRepository(con), actor, admin or state['mode'] != 'read_only'

    monkeypatch.setattr(service, 'transaction', transaction)
    def preflight(actor, **target):
        with transaction(actor, **target, write=True):
            pass
    monkeypatch.setattr(service, 'preflight', preflight)
    def acquire(user=applicant, *, date='2025-01-01'):
        _, claim = repo.create_ownership_claim(user, individual, ownership_kind='acquire', occurred_at=date)
        with repo.connect() as con:
            con.execute('''INSERT INTO acquire_applications(revision,applicant_id,individual_id,original_individual_id,
                serial,challenge,expires_at,created_at,status,prompt_version,claim_id)
                VALUES (?,?,?,?,'PRIVATE-001','FIXTURE',0,'2025-01-01','accepted','synthetic',?)''',
                ('fixture-' + str(claim), user, individual, individual, claim))
        return claim
    claim = acquire()
    return repo, service, owner, applicant, competitor, admin, outsider, individual, claim, state, acquire


def begin(workflow, *, claimant=None, claim_id=None):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    applicant, claim = claimant or applicant, claim_id or claim
    repo.set_claim_response(claim, owner, 'negative', 'The guitar is on loan.')
    data = OPEN | {'revision': service.option(applicant, claim)['revision']}
    return service.submit(applicant, claim, data, PDF, 'purchase.pdf')['detail'], data


def decision(service, admin, detail, action, winner=None):
    return service.decide(admin, int(detail['id']), {'version': detail['version'],
        'round_number': detail['round']['number'], 'action': action, 'reason': 'Reviewed the supplied records.',
        'winner_claim_id': str(winner) if winner else None})['detail']


def evidence(service, user, detail, claim, *, attachment=b''):
    return service.submit(user, claim, {'revision': None, 'case_id': detail['id'], 'version': detail['version'],
        'round_number': detail['round']['number'], 'explanation': 'My explanation', 'summary': 'My summary'},
        attachment, '')['detail']


def counts(repo):
    with repo.connect() as con:
        return {table: con.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in
            ('ownership_disputes', 'ownership_dispute_evidence', 'ownership_dispute_events', 'notifications', 'claim_admin_actions')}


def test_option_acknowledgement_fresh_decline_and_retries(workflow):
    repo, service, owner, applicant, _, _, outsider, _, claim, _, _ = workflow
    option = service.option(applicant, claim)
    assert option['eligible'] and not option['can_acknowledge'] and not option['can_appeal']
    assert option['wait_days'] == 14 and len(option['revision']) == 64
    repo.set_claim_response(claim, owner, 'negative', 'My signed loan agreement.')
    option = service.option(applicant, claim)
    assert option['can_acknowledge'] and option['can_appeal']
    assert service.options(applicant)['items'] == [option]
    assert service.options(outsider)['items'] == []
    for actor in (owner, outsider):
        with pytest.raises(GuitarMissing):
            service.option(actor, claim)
        with pytest.raises(GuitarMissing):
            service.acknowledge(actor, claim, {'revision': option['revision']})
    payload = {'revision': option['revision']}
    result = service.acknowledge(applicant, claim, payload)['option']
    assert result['decline']['acknowledged_at']
    assert not result['can_acknowledge'] and not result['can_appeal']
    assert service.options(applicant)['items'] == []
    before = counts(repo)
    with pytest.raises(ClaimConflict):
        service.acknowledge(applicant, claim, payload)
    assert counts(repo) == before


def test_exact_14_day_wait_is_claim_creation_not_application_or_acquisition(workflow, monkeypatch):
    repo, service, _, applicant, _, _, _, _, claim, _, _ = workflow
    since = datetime(2025, 1, 1, tzinfo=timezone.utc)
    class Frozen(datetime):
        value = since + timedelta(days=14) - timedelta(microseconds=1)
        @classmethod
        def now(cls, tz=None):
            return cls.value
    monkeypatch.setattr(disputes, 'datetime', Frozen)
    with repo.connect() as con:
        con.execute('UPDATE claims SET created_at=? WHERE id=?', (since.isoformat(), claim))
    option = service.option(applicant, claim)
    assert not option['can_appeal'] and option['wait_until'] == '2025-01-15T00:00:00+00:00'
    with pytest.raises(ClaimConflict):
        service.submit(applicant, claim, OPEN | {'revision': option['revision']}, PDF)
    Frozen.value += timedelta(microseconds=1)
    assert service.option(applicant, claim)['can_appeal']
    result = service.submit(applicant, claim, OPEN | {'revision': option['revision']}, PDF)['detail']
    assert result['status'] == 'open'


def test_first_attachment_mandatory_and_open_retry_does_not_duplicate(workflow):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    repo.set_claim_response(claim, owner, 'negative', 'Loan')
    data = OPEN | {'revision': service.option(applicant, claim)['revision']}
    with pytest.raises(ValueError, match='attachment'):
        service.submit(applicant, claim, data)
    assert counts(repo)['ownership_disputes'] == 0
    detail = service.submit(applicant, claim, data, PDF)['detail']
    before = counts(repo)
    with pytest.raises(ClaimConflict):
        service.submit(applicant, claim, data, PDF)
    assert counts(repo) == before
    assert service.option(applicant, claim)['case_id'] == detail['id']
    assert not service.option(applicant, claim)['eligible']
    assert service.options(applicant)['items'] == []


def test_revision_includes_decline_and_current_evaluator_inputs(workflow):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    repo.set_claim_response(claim, owner, 'negative', 'Original decline')
    changes = [
        ("UPDATE ownership_declines SET reason='Different decline' WHERE claim_id=?", claim),
        ("UPDATE claim_source_evidence SET effective_date='2024-01-01' WHERE claim_id=?", claim),
        ("UPDATE claims SET admin_verification=1 WHERE id=?", claim),
    ]
    for query, target in changes:
        revision = service.option(applicant, claim)['revision']
        with repo.connect() as con:
            con.execute(query, (target,))
        assert service.option(applicant, claim)['revision'] != revision
        for action in (lambda: service.acknowledge(applicant, claim, {'revision': revision}),
                       lambda: service.submit(applicant, claim, OPEN | {'revision': revision}, PDF)):
            with pytest.raises(ClaimConflict):
                action()


def test_private_evidence_summary_publication_and_no_bytea_detail(workflow):
    repo, service, owner, applicant, _, admin, outsider, _, claim, state, _ = workflow
    detail, _ = begin(workflow)
    case = int(detail['id'])
    own = detail['evidence'][0]
    assert own['explanation'] == OPEN['explanation'] and own['summary'] == OPEN['summary']
    assert own['has_attachment'] is True
    assert service.detail(owner, case)['evidence'] == []
    with pytest.raises(GuitarMissing):
        service.detail(outsider, case)
    with pytest.raises(GuitarMissing):
        service.attachment(owner, int(own['id']))
    assert service.attachment(applicant, int(own['id'])) == dict(content=PDF, content_type='application/pdf', filename='document.pdf')
    admin_view = service.detail(admin, case, admin=True)
    publication = {'version': admin_view['version'], 'round_number': admin_view['round']['number'], 'summary': 'Reviewed purchase summary'}
    result = service.publish(admin, int(own['id']), publication)['detail']
    exposed = service.detail(owner, case)['evidence'][0]
    assert exposed['published_summary'] == 'Reviewed purchase summary'
    assert not set(exposed) & {'explanation', 'summary', 'filename', 'content_type', 'has_attachment', 'content'}
    before = counts(repo)
    for value in (publication, publication | {'version': result['version']}):
        with pytest.raises(ClaimConflict):
            service.publish(admin, int(own['id']), value)
    assert counts(repo) == before
    state['trace'].clear()
    service.detail(admin, case, admin=True)
    selects = [q.lower() for q in state['trace'] if 'select' in q.lower() and 'ownership_dispute_evidence' in q.lower()]
    assert selects and not any('select *' in q or 'select e.*' in q or 'select content' in q for q in selects)


def test_round_party_submission_cas_and_additional_round(workflow):
    repo, service, owner, applicant, _, admin, _, _, claim, _, _ = workflow
    detail, _ = begin(workflow)
    owner_view = service.detail(owner, int(detail['id']))
    parties = owner_view['round']['parties']
    assert [p['can_submit'] for p in parties if p['user_id'] == str(owner)] == [True]
    assert not any(p['can_submit'] for p in detail['round']['parties'])
    with pytest.raises(ValueError, match='Both parties'):
        decision(service, admin, detail, 'request_evidence')
    with pytest.raises(ValueError, match='already submitted'):
        evidence(service, applicant, detail, claim)
    reviewing = evidence(service, owner, owner_view, claim)
    assert reviewing['round']['phase'] == 'reviewing'
    before = counts(repo)
    with pytest.raises(ClaimConflict):
        evidence(service, owner, owner_view, claim)
    assert counts(repo) == before
    next_round = decision(service, admin, reviewing, 'request_evidence')
    assert next_round['round']['number'] == '2'
    assert len(next_round['rounds']) == 2
    assert next_round['round']['request_reason'] == 'Reviewed the supplied records.'
    with pytest.raises(ClaimConflict):
        evidence(service, applicant, reviewing, claim)
    latest = service.detail(applicant, int(detail['id']))
    result = evidence(service, applicant, latest, claim)
    assert result['evidence'][-1]['has_attachment'] is False
    assert result['evidence'][-1]['round_number'] == '2'


def test_multiple_applicants_isolated_in_one_case_and_frozen_ownership(workflow):
    repo, service, owner, applicant, competitor, admin, _, individual, claim, _, acquire = workflow
    other_claim = acquire(competitor)
    repo.set_claim_response(other_claim, owner, 'negative', 'Competitor private decline')
    detail, _ = begin(workflow)
    first = int(detail['id'])
    option = service.option(competitor, other_claim)
    joined = service.submit(competitor, other_claim, OPEN | {'revision': option['revision'],
        'explanation': 'Competitor private evidence'}, PDF)['detail']
    assert joined['id'] == detail['id']
    assert {c['claim_id'] for c in joined['claims']} == {str(other_claim)}
    assert {e['claim_id'] for e in joined['evidence']} == {str(other_claim)}
    mine = service.detail(applicant, first)
    assert 'Competitor private' not in json.dumps(mine)
    assert len(service.detail(owner, first)['claims']) == 2
    assert len(service.detail(admin, first, admin=True)['evidence']) == 2
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == owner
    for create in (lambda: acquire(), lambda: repo.create_transfer(owner, individual, competitor)):
        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            create()


@pytest.mark.parametrize('winner', ['owner', 'applicant'])
def test_decision_without_all_evidence_atomic_authority_and_reopen(workflow, winner):
    repo, service, owner, applicant, competitor, admin, _, individual, claim, _, _ = workflow
    detail, _ = begin(workflow)
    assert detail['round']['phase'] == 'collecting'
    resolved = decision(service, admin, detail, winner, claim if winner == 'applicant' else None)
    assert resolved['status'] == 'resolved' and resolved['can_reopen']
    chosen = owner if winner == 'owner' else applicant
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == chosen
    with repo.connect() as con:
        row = con.execute('SELECT * FROM claims WHERE id=?', (claim,)).fetchone()
        assert row['author_user_id'] == applicant
        assert row['verification_status'] == ('positive' if winner == 'applicant' else 'negative')
        audit = con.execute('SELECT * FROM claim_admin_actions WHERE claim_id=? ORDER BY id DESC', (claim,)).fetchone()
        assert audit['actor'] == 'identity-platform:' + str(admin)
        assert con.execute("SELECT actor_id FROM ownership_dispute_events WHERE kind='resolved'").fetchone()[0] == admin
    for who in (owner, applicant, competitor):
        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            repo.set_claim_response(claim, who, 'positive')
    before = counts(repo)
    with pytest.raises(ClaimConflict):
        decision(service, admin, detail, winner, claim if winner == 'applicant' else None)
    assert counts(repo) == before
    reopened = decision(service, admin, resolved, 'reopen')
    assert reopened['round']['number'] == '2' and reopened['locked_owner_id'] == str(chosen)
    assert reopened['owner_id'] == str(owner) and len(reopened['evidence']) == 1
    finished = decision(service, admin, reopened, 'owner')
    transfer = repo.create_transfer(owner, individual, competitor)
    repo.resolve_transfer(transfer, competitor, 'accept')
    assert not service.detail(admin, int(finished['id']), admin=True)['can_reopen']
    with pytest.raises(ValueError, match='Current Owner changed'):
        decision(service, admin, finished, 'reopen')


def test_failed_audit_or_notification_rolls_back_all_decision_changes(workflow):
    repo, service, owner, applicant, _, admin, _, individual, claim, _, _ = workflow
    detail, _ = begin(workflow)
    before = counts(repo)
    with repo.connect() as con:
        con.execute("CREATE TRIGGER fail_dispute_notice BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic failure'):
        decision(service, admin, detail, 'applicant', claim)
    assert counts(repo) == before
    assert service.detail(applicant, int(detail['id']))['version'] == detail['version']
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == owner


def test_concurrent_same_open_has_one_winner(workflow):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    repo.set_claim_response(claim, owner, 'negative', 'Loan')
    data = OPEN | {'revision': service.option(applicant, claim)['revision']}
    def run(_):
        try:
            return service.submit(applicant, claim, data, PDF)['detail']['id']
        except ClaimConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert len([r for r in results if r]) == 1
    assert counts(repo)['ownership_disputes'] == counts(repo)['ownership_dispute_evidence'] == 1


def test_bytes_limit_case_count_and_image_sanitization(workflow):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    repo.set_claim_response(claim, owner, 'negative', 'Loan')
    data = OPEN | {'revision': service.option(applicant, claim)['revision']}
    with pytest.raises(ValueError):
        service.submit(applicant, claim, data, b'x' * (disputes.MAX_BYTES + 1))
    result = service.submit(applicant, claim, data, image_bytes(), 'unsafe.html')['detail']
    photo = service.attachment(applicant, int(result['evidence'][0]['id']))
    assert photo['content'].startswith(b'\xff\xd8') and photo['filename'] == 'photo.jpg'
    with repo.connect() as con:
        for _ in range(99):
            con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,claim_id,author_id,explanation,summary,created_at)
                VALUES (?,?,?,'Synthetic','Synthetic','2025-01-01')''', (int(result['id']), claim, applicant))
    with pytest.raises(ValueError, match='100-submission'):
        evidence(service, owner, service.detail(owner, int(result['id'])), claim)


@pytest.mark.parametrize('mode', ['read_only', 'offline'])
def test_modes_read_only_and_offline(workflow, mode):
    repo, service, owner, applicant, _, admin, _, _, claim, state, _ = workflow
    detail, _ = begin(workflow)
    state['mode'] = mode
    if mode == 'offline':
        with pytest.raises(ServiceRestricted):
            service.detail(applicant, int(detail['id']))
    else:
        view = service.detail(owner, int(detail['id']))
        assert not view['can_write'] and not any(p['can_submit'] for p in view['round']['parties'])
    with pytest.raises(ServiceRestricted):
        evidence(service, owner, detail, claim)
    assert service.detail(admin, int(detail['id']), admin=True)['can_write']


@pytest.mark.parametrize('status', ['ban', 'silent_ban'])
def test_ban_silent_ban_and_admin_role_revocation(workflow, status):
    repo, service, _, applicant, _, admin, _, _, _, state, _ = workflow
    detail, _ = begin(workflow)
    with repo.connect() as con:
        con.execute('UPDATE users SET ban_status=? WHERE id=?', (status, applicant))
    for action in (lambda: service.options(applicant), lambda: service.detail(applicant, int(detail['id'])),
                   lambda: service.attachment(applicant, int(detail['evidence'][0]['id']))):
        with pytest.raises(PermissionError):
            action()
    state['admin'] = None
    with pytest.raises(PermissionError):
        service.detail(admin, int(detail['id']), admin=True)
    with pytest.raises(PermissionError):
        decision(service, admin, detail, 'owner')


def test_dto_all_bigint_fields_strings_and_unknown_private_keys_dropped(workflow):
    _, service, _, applicant, _, admin, _, _, _, _, _ = workflow
    detail, _ = begin(workflow)
    view = service.detail(admin, int(detail['id']), admin=True)
    view.update(storage_path='private://secret', account_role='god', content=PDF)
    view['evidence'][0].update(content=PDF, secret='hidden')
    projected = result_projection('detail', view)
    assert not set(projected) & {'storage_path', 'account_role', 'content'}
    assert not set(projected['evidence'][0]) & {'content', 'secret'}
    def identifiers(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k == 'id' or k.endswith('_id') or k in ('version', 'number', 'round_number'):
                    assert v is None or isinstance(v, str), (k, v)
                identifiers(v)
        elif isinstance(value, list):
            for item in value:
                identifiers(item)
    identifiers(projected)
    assert int(projected['id']) > 2**53
    assert service.list(applicant)['items'][0]['id'] == projected['id']


@pytest.mark.parametrize('bad', [0, -1, True, 1.5, '2', 2**63])
def test_invalid_positional_identifiers_before_database(bad):
    service = CloudDisputes(None, None)
    service.transaction = Mock(side_effect=AssertionError('Database must not be reached'))
    for method in ('option', 'detail', 'attachment'):
        with pytest.raises(ValueError):
            getattr(service, method)('actor', bad)


@pytest.mark.parametrize('bad', [True, 1, 1.0, '01', '-1', '0', '1e3', '９', str(2**63), '1' * 200])
def test_strict_decimal_payload_ids(bad):
    with pytest.raises(ValueError):
        submission_payload(OPEN | {'revision': None, 'case_id': bad, 'version': '1', 'round_number': '1'})
    with pytest.raises(ValueError):
        decision_payload({'version': bad, 'round_number': '1', 'action': 'owner', 'reason': 'Reviewed', 'winner_claim_id': None})


@pytest.mark.parametrize('bad', ['', ' ', '\x00', '\x01', '\x7f', '\ud800', 'x' * 8001])
def test_strict_plaintext_and_utf8(bad):
    with pytest.raises((ValueError, UnicodeError)):
        submission_payload(OPEN | {'revision': 'a' * 64, 'explanation': bad})


def test_strict_payload_shapes_and_router_preserves_wire_ids():
    samples = [(acknowledgment_payload, {'revision': 'a' * 64}),
        (submission_payload, OPEN | {'revision': 'a' * 64}),
        (publication_payload, {'version': '1', 'round_number': '1', 'summary': 'Reviewed'}),
        (decision_payload, {'version': '1', 'round_number': '1', 'action': 'owner', 'reason': 'Reviewed', 'winner_claim_id': None})]
    for validator, value in samples:
        assert validator(value)
        for field in value:
            with pytest.raises(ValueError):
                validator({k: v for k, v in value.items() if k != field})
        with pytest.raises(ValueError):
            validator(value | {'user_id': str(BIG)})
    payload = samples[-1][1]
    assert request_projection('decide', payload)['version'] == '1'


def test_postgres_generated_ids_adapter():
    raw = Mock()
    cursor = raw.execute.return_value
    cursor.fetchone.return_value = {'id': BIG}
    connection = DisputeConnection(raw)
    for table in ('ownership_disputes', 'ownership_dispute_rounds', 'ownership_dispute_evidence', 'ownership_dispute_events'):
        result = connection.execute('INSERT INTO ' + table + '(created_at) VALUES (?)', ('today',))
        assert result.lastrowid == BIG
        assert raw.execute.call_args.args == ('INSERT INTO ' + table + '(created_at) VALUES (%s) RETURNING id', ('today',))


def test_case_byte_budget_counts_existing_bytes_before_insert(workflow, monkeypatch):
    repo, service, owner, _, _, _, _, _, claim, _, _ = workflow
    detail, _ = begin(workflow)
    original = service.transaction
    class ByteBudget:
        def __init__(self, connection):
            self.connection = connection
        def execute(self, sql, args=()):
            if 'SUM(length(content))' in sql:
                return Mock(fetchone=Mock(return_value=(256 * 1024 * 1024,)))
            return self.connection.execute(sql, args)
    @contextmanager
    def transaction(*args, **kwargs):
        with original(*args, **kwargs) as (bound, user, can_write):
            yield BoundRepository(ByteBudget(bound.connection)), user, can_write
    monkeypatch.setattr(service, 'transaction', transaction)
    before = counts(repo)
    with pytest.raises(ValueError, match='256 MB'):
        evidence(service, owner, detail, claim, attachment=PDF)
    assert counts(repo) == before


def test_dto_refuses_oversized_collections_instead_of_truncating(workflow):
    _, service, _, applicant, _, admin, _, _, _, _, _ = workflow
    detail, _ = begin(workflow)
    listing = service.list(applicant)
    with pytest.raises(RuntimeError):
        result_projection('list', listing | {'items': listing['items'] * 51})
    admin_view = service.detail(admin, int(detail['id']), admin=True)
    for key, limit in (('rounds', 256), ('events', 1024), ('evidence', 100), ('claims', 100)):
        with pytest.raises(RuntimeError):
            result_projection('detail', admin_view | {key: admin_view[key] * (limit + 1)})


def test_legacy_oversized_history_reader_is_bounded(workflow):
    repo, service, _, applicant, _, _, _, _, _, state, _ = workflow
    detail, _ = begin(workflow)
    with repo.connect() as con:
        for number in range(2, 258):
            con.execute('''INSERT INTO ownership_dispute_rounds(dispute_id,number,phase,request_reason,created_at)
                VALUES (?,?,'collecting','','2025-01-01')''', (int(detail['id']), number))
    state['trace'].clear()
    with pytest.raises(RuntimeError, match='bounded detail'):
        service.detail(applicant, int(detail['id']))
    history = [q for q in state['trace'] if 'SELECT id,number,phase' in q]
    assert history and all('LIMIT 257' in q for q in history)


def test_detail_sql_only_selects_author_private_text(workflow):
    _, service, owner, _, _, _, _, _, _, state, _ = workflow
    detail, _ = begin(workflow)
    state['trace'].clear()
    service.detail(owner, int(detail['id']))
    query = next(q for q in state['trace'] if 'SELECT e.id,e.claim_id' in q)
    assert 'CASE WHEN 0=1 OR e.author_id=' + str(owner) + ' THEN e.explanation ELSE NULL END' in query
    assert 'e.published_at IS NOT NULL' in query and 'LIMIT 101' in query


def test_same_decline_same_timestamp_new_notice_invalidates_revision(workflow):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    repo.set_claim_response(claim, owner, 'negative', 'Unchanged reason')
    old = service.option(applicant, claim)['revision']
    with repo.connect() as con:
        decline = dict(con.execute('SELECT * FROM ownership_declines WHERE claim_id=?', (claim,)).fetchone())
        con.execute('''INSERT INTO notifications(recipient_user_id,actor_user_id,notification_type,individual_id,
            claim_id,title,body,created_at) SELECT recipient_user_id,actor_user_id,notification_type,
            individual_id,claim_id,title,body,created_at FROM notifications WHERE claim_id=? ORDER BY id DESC LIMIT 1''', (claim,))
        assert dict(con.execute('SELECT * FROM ownership_declines WHERE claim_id=?', (claim,)).fetchone()) == decline
    assert service.option(applicant, claim)['revision'] != old
    with pytest.raises(ClaimConflict):
        service.acknowledge(applicant, claim, {'revision': old})


def test_wrong_application_kind_rejected_in_direct_option(workflow):
    repo, service, _, applicant, _, _, _, _, claim, _, _ = workflow
    with repo.connect() as con:
        con.execute("UPDATE acquire_applications SET request_kind='listing' WHERE claim_id=?", (claim,))
    assert service.options(applicant)['items'] == []
    with pytest.raises(GuitarMissing):
        service.option(applicant, claim)


def test_service_payloads_rejected_before_transaction_or_image_processing():
    service = CloudDisputes(None, None)
    service.transaction = Mock(side_effect=AssertionError('No database expected.'))
    bad = {'user_id': '123'}
    for action in (lambda: service.acknowledge('actor', 1, bad), lambda: service.submit('actor', 1, bad),
                   lambda: service.publish('actor', 1, bad), lambda: service.decide('actor', 1, bad)):
        with pytest.raises(ValueError):
            action()
    service.transaction.assert_not_called()


def test_image_normalization_is_serialized_and_denied_before_decode(workflow, monkeypatch):
    from ygc import cloud_disputes
    assert cloud_disputes.UPLOADS.acquire(blocking=False)
    try:
        assert not cloud_disputes.UPLOADS.acquire(blocking=False)
    finally:
        cloud_disputes.UPLOADS.release()
    _, service, owner, applicant, _, _, outsider, _, claim, state, _ = workflow
    data = OPEN | {'revision': service.option(applicant, claim)['revision']}
    normalize = Mock(side_effect=AssertionError('Denied requests must not decode images'))
    monkeypatch.setattr(disputes, 'validate_submission', normalize)
    with pytest.raises(GuitarMissing):
        service.submit(outsider, claim, data, image_bytes())
    state['mode'] = 'offline'
    with pytest.raises(ServiceRestricted):
        service.submit(applicant, claim, data, image_bytes())
    state['mode'] = 'read_only'
    with pytest.raises(ServiceRestricted):
        service.submit(applicant, claim, data, image_bytes())
    normalize.assert_not_called()
