"""Portable immutable-original integrity and transactional retention checks."""
from contextlib import contextmanager
import hashlib
import json
import sqlite3
from unittest.mock import Mock

import pytest

from dispute_storage_fixtures import MemoryOriginalStorage
from test_cloud_disputes import workflow, begin, evidence, counts, OPEN, PDF
from ygc.cloud_dispute_storage import (CloudDisputeStorage, OriginalUnavailable,
    original_reference, read_original, verify_original, ORIGINAL_COLUMNS)
from ygc.cloud_storage import ObjectReference
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_backup_preflight import BackupCapacityError
from ygc.claim_revision import ClaimConflict
from ygc.db.postgres_ownership import BoundRepository
from ygc import disputes


def original_row(**changes):
    return dict(evidence_id=1, object_scope='content', object_name='media/' + 'a' * 32,
                object_generation=2**53 + 1, byte_size=len(PDF), content_type='application/pdf',
                sha256=hashlib.sha256(PDF).hexdigest(), created_at='2026-10-07T00:00:00+00:00') | changes


def test_original_exact_generation_and_verified_bytes():
    row = original_row()
    storage = Mock()
    storage.get.return_value = PDF
    ref = original_reference(row)
    assert ref.generation == 2**53 + 1
    assert read_original(storage, row) == PDF
    storage.get.assert_called_once_with(ref)
    verify_original(storage, row)
    assert storage.delete.call_count == 0


@pytest.mark.parametrize('changes', [
    {'evidence_id': True}, {'evidence_id': 0}, {'evidence_id': 2**63},
    {'object_scope': 'accounts'}, {'object_name': 'https://private.example/original'},
    {'object_name': 'media/' + 'a' * 31}, {'object_generation': 0},
    {'object_generation': True}, {'object_generation': 2**63}, {'object_generation': '123'},
    {'byte_size': 0}, {'byte_size': True}, {'byte_size': disputes.MAX_BYTES + 1},
    {'content_type': 'text/html'}, {'sha256': 'A' * 64}, {'sha256': 'a' * 63},
    {'created_at': None}, {'created_at': ''},
])
def test_malformed_reference_rejected_before_storage(changes):
    storage = Mock()
    with pytest.raises(OriginalUnavailable):
        read_original(storage, original_row(**changes))
    storage.get.assert_not_called()


@pytest.mark.parametrize('data', [b'x' * len(PDF), PDF + b'x', PDF[:-1], memoryview(PDF), 'not bytes'])
def test_hash_and_size_mismatch_fail_closed(data):
    storage = Mock(get=Mock(return_value=data))
    with pytest.raises(OriginalUnavailable):
        read_original(storage, original_row())
    storage.delete.assert_not_called()


def test_storage_exception_is_generic_without_reference():
    storage = Mock(get=Mock(side_effect=ValueError('private gs://bucket/path')))
    with pytest.raises(OriginalUnavailable) as exc:
        read_original(storage, original_row())
    assert 'bucket' not in str(exc.value) and 'gs://' not in str(exc.value)
    with pytest.raises(OriginalUnavailable):
        read_original(None, original_row())


@pytest.mark.parametrize('reference', [
    None, {'scope': 'content'},
    ObjectReference('accounts', 'media/' + 'a' * 32, 1, len(PDF), 'application/pdf'),
    ObjectReference('content', 'media/' + 'a' * 32, 1, 1, 'application/pdf'),
    ObjectReference('content', 'media/' + 'a' * 32, 1, len(PDF), 'image/jpeg'),
])
def test_invalid_upload_response_is_retained_without_database_reference(reference):
    storage = Mock(put=Mock(return_value=reference))
    connection = Mock()
    with pytest.raises(OriginalUnavailable):
        CloudDisputeStorage(storage).store(connection, 1, PDF, 'application/pdf')
    storage.delete.assert_not_called()
    connection.execute.assert_not_called()


def test_new_original_reference_only_and_dto_never_exposes_it(workflow):
    repo, service, _, applicant, _, admin, _, _, _, _, _ = workflow
    detail, _ = begin(workflow)
    attachment_id = int(detail['evidence'][0]['id'])
    with repo.connect() as con:
        row = dict(con.execute('SELECT * FROM ownership_dispute_originals WHERE evidence_id=?', (attachment_id,)).fetchone())
        assert tuple(row) == ORIGINAL_COLUMNS
        assert con.execute('SELECT content FROM ownership_dispute_evidence WHERE id=?', (attachment_id,)).fetchone()[0] is None
        assert row['sha256'] == hashlib.sha256(PDF).hexdigest()
    assert service.attachment(applicant, attachment_id)['content'] == PDF
    assert service.attachment(admin, attachment_id, admin=True)['content'] == PDF
    for response in (detail, service.detail(admin, int(detail['id']), admin=True), service.list(applicant)):
        payload = json.dumps(response)
        assert row['object_name'] not in payload and row['sha256'] not in payload
        assert not any(field in payload for field in ('object_scope', 'object_generation', 'byte_size', 'sha256'))
    assert service.storage.deletions == []


def test_missing_storage_has_no_bytea_fallback(workflow):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    repo.set_claim_response(claim, owner, 'negative', 'Loan')
    data = OPEN | {'revision': service.option(applicant, claim)['revision']}
    service.storage = None
    before = counts(repo)
    with pytest.raises(OriginalUnavailable):
        service.submit(applicant, claim, data, PDF)
    assert counts(repo) == before


def test_stale_submission_rejected_without_another_upload(workflow):
    _, service, _, applicant, _, _, _, _, claim, _, _ = workflow
    _, data = begin(workflow)
    with pytest.raises(ClaimConflict):
        service.submit(applicant, claim, data, PDF)
    assert len(service.storage.uploads) == 1


def test_legacy_backup_capacity_blocks_submission_before_upload_or_mutation(workflow):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    detail, _ = begin(workflow)
    with repo.connect() as con:
        # Model historical BYTEA that cannot fit the unchanged JSONL budget.
        con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,claim_id,author_id,
            explanation,summary,content,content_type,created_at)
            VALUES (?,?,?,'Legacy','Legacy',?,'application/pdf','2025')''',
            (int(detail['id']), claim, applicant, b'%PDF-' + b'x' * (7 * 1024 * 1024)))
    before, uploads = counts(repo), len(service.storage.uploads)
    with pytest.raises(BackupCapacityError) as exc:
        evidence(service, owner, detail, claim, attachment=PDF)
    assert exc.value.code == 'legacy_evidence_line_limit'
    assert counts(repo) == before and len(service.storage.uploads) == uploads


def test_legacy_bytea_download_still_works_without_storage(workflow):
    repo, service, _, applicant, _, admin, _, _, _, _, _ = workflow
    detail, _ = begin(workflow)
    attachment_id = int(detail['evidence'][0]['id'])
    # Model an existing pre-003 row without converting any application data.
    with repo.connect() as con:
        con.execute('DELETE FROM ownership_dispute_originals WHERE evidence_id=?', (attachment_id,))
        con.execute('UPDATE ownership_dispute_evidence SET content=? WHERE id=?', (PDF, attachment_id))
    service.storage = None
    assert service.attachment(applicant, attachment_id)['content'] == PDF
    assert service.attachment(admin, attachment_id, admin=True)['content'] == PDF
    assert service.detail(applicant, int(detail['id']))['evidence'][0]['has_attachment']


@pytest.mark.parametrize('damage', ['missing', 'size', 'hash', 'mime', 'dual'])
def test_corrupt_original_metadata_never_serves_bytes(workflow, damage):
    repo, service, _, applicant, _, _, _, _, _, _, _ = workflow
    detail, _ = begin(workflow)
    attachment_id = int(detail['evidence'][0]['id'])
    with repo.connect() as con:
        if damage == 'missing':
            con.execute('DELETE FROM ownership_dispute_originals')
        elif damage == 'dual':
            con.execute('UPDATE ownership_dispute_evidence SET content=?', (PDF,))
        else:
            column, value = {'size': ('byte_size', 1), 'hash': ('sha256', '0' * 64),
                             'mime': ('content_type', 'image/jpeg')}[damage]
            con.execute('UPDATE ownership_dispute_originals SET ' + column + '=?', (value,))
    with pytest.raises(OriginalUnavailable):
        service.attachment(applicant, attachment_id)
    assert not service.storage.deletions


def test_download_occurs_inside_authorization_fences(workflow, monkeypatch):
    _, service, _, applicant, _, _, _, _, _, _, _ = workflow
    detail, _ = begin(workflow)
    active = []
    transaction = service.transaction
    @contextmanager
    def fenced(*args, **kwargs):
        with transaction(*args, **kwargs) as context:
            active.append(True)
            try:
                yield context
            finally:
                active.pop()
    get = service.storage.get
    def checked(reference):
        assert active
        return get(reference)
    monkeypatch.setattr(service, 'transaction', fenced)
    monkeypatch.setattr(service.storage, 'get', checked)
    assert service.attachment(applicant, int(detail['evidence'][0]['id']))['content'] == PDF


@pytest.mark.parametrize('denied', ['owner', 'outsider', 'ban', 'silent_ban', 'revoked_admin', 'offline'])
def test_current_access_denial_never_reads_original(workflow, denied):
    from ygc.db.postgres_operations import ServiceRestricted
    repo, service, owner, applicant, _, admin, outsider, _, _, state, _ = workflow
    detail, _ = begin(workflow)
    actor, admin_access = applicant, False
    if denied in ('owner', 'outsider'):
        actor = owner if denied == 'owner' else outsider
    elif denied in ('ban', 'silent_ban'):
        with repo.connect() as con:
            con.execute('UPDATE users SET ban_status=? WHERE id=?', (denied, applicant))
    elif denied == 'revoked_admin':
        actor, admin_access, state['admin'] = admin, True, None
    elif denied == 'offline':
        state['mode'] = 'offline'
    with pytest.raises((PermissionError, GuitarMissing, ServiceRestricted)):
        service.attachment(actor, int(detail['evidence'][0]['id']), admin=admin_access)
    assert service.storage.reads == []


@pytest.mark.parametrize('stage', ['upload_response', 'ref_insert', 'notification', 'rollback', 'commit_response'])
def test_uncertain_and_failed_submissions_never_delete_originals(workflow, monkeypatch, stage):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    repo.set_claim_response(claim, owner, 'negative', 'Loan')
    data = OPEN | {'revision': service.option(applicant, claim)['revision']}
    if stage == 'upload_response':
        put = service.storage.put
        def unknown(*args, **kwargs):
            put(*args, **kwargs)
            raise TimeoutError('Upload reply lost')
        monkeypatch.setattr(service.storage, 'put', unknown)
    elif stage in ('ref_insert', 'notification'):
        with repo.connect() as con:
            if stage == 'ref_insert':
                con.execute("CREATE TRIGGER fail_reference BEFORE INSERT ON ownership_dispute_originals BEGIN SELECT RAISE(ABORT,'synthetic'); END")
            else:
                con.execute("CREATE TRIGGER fail_notice BEFORE INSERT ON notifications WHEN NEW.body LIKE '%evidence submitted%' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    else:
        transaction = service.transaction
        @contextmanager
        def failed(*args, **kwargs):
            with transaction(*args, **kwargs) as context:
                yield context
                if stage == 'rollback':
                    raise RuntimeError('Synthetic rollback')
            raise RuntimeError('Commit response lost')
        monkeypatch.setattr(service, 'transaction', failed)
        # Keep preflight separate so failure occurs after the actual upload.
        monkeypatch.setattr(service, 'preflight', lambda *args, **kwargs: None)
    with pytest.raises((OriginalUnavailable, sqlite3.IntegrityError, RuntimeError)):
        service.submit(applicant, claim, data, PDF)
    assert len(service.storage.objects) == 1 and service.storage.deletions == []
    with repo.connect() as con:
        expected = 1 if stage == 'commit_response' else 0
        assert con.execute('SELECT COUNT(*) FROM ownership_dispute_originals').fetchone()[0] == expected
        assert con.execute('SELECT COUNT(*) FROM ownership_dispute_evidence').fetchone()[0] == expected


def test_mixed_originals_case_quota_counts_both_backends_before_upload(workflow):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    detail, _ = begin(workflow)
    mib = 1024 * 1024
    with repo.connect() as con:
        con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,claim_id,author_id,explanation,summary,content,content_type,created_at)
            VALUES (?,?,?,'Legacy','Legacy',?,'application/pdf','2025')''', (int(detail['id']), claim, applicant, b'x' * mib))
        for i, size in enumerate([12*mib] * 21 + [2*mib], 100):
            eid = con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,claim_id,author_id,explanation,summary,content_type,created_at)
                VALUES (?,?,?,'Stored','Stored','application/pdf','2026')''', (int(detail['id']), claim, applicant)).lastrowid
            row = original_row(evidence_id=eid, object_name='media/' + f'{i:032x}', byte_size=size)
            con.execute('INSERT INTO ownership_dispute_originals VALUES (?,?,?,?,?,?,?,?)', tuple(row[key] for key in ORIGINAL_COLUMNS))
    uploads = len(service.storage.uploads)
    with pytest.raises(ValueError, match='256 MB'):
        evidence(service, owner, detail, claim, attachment=b'%PDF-' + b'x' * (mib - 5))
    assert len(service.storage.uploads) == uploads
    remaining = mib - len(PDF)
    evidence(service, owner, detail, claim, attachment=b'%PDF-' + b'x' * (remaining - 5))
    with repo.connect() as con:
        legacy = con.execute('SELECT SUM(length(content)) FROM ownership_dispute_evidence').fetchone()[0]
        external = CloudDisputeStorage(service.storage).additional_bytes(con, int(detail['id']))
        assert legacy + external == 256 * mib
    assert len(service.storage.uploads) == uploads + 1


def test_maximum_attachment_is_external_not_large_bytea(workflow):
    repo, service, owner, applicant, _, _, _, _, claim, _, _ = workflow
    repo.set_claim_response(claim, owner, 'negative', 'Loan')
    data = OPEN | {'revision': service.option(applicant, claim)['revision']}
    content = b'%PDF-' + b'x' * (disputes.MAX_BYTES - 5)
    result = service.submit(applicant, claim, data, content)['detail']
    with repo.connect() as con:
        assert con.execute('SELECT SUM(length(content)) FROM ownership_dispute_evidence').fetchone()[0] is None
        assert con.execute('SELECT byte_size FROM ownership_dispute_originals').fetchone()[0] == disputes.MAX_BYTES
    assert service.attachment(applicant, int(result['evidence'][0]['id']))['content'] == content
