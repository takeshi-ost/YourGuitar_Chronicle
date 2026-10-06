"""Owner service and HTTP regressions using disposable, in-process SQLite only.

The adapter drops only the PostgreSQL row-lock suffix; these tests exercise the
real shared Claim/decline/evaluator transaction without opening a server socket.
PostgreSQL lock behavior remains the separate integration suite's responsibility.
"""
from contextlib import contextmanager
import json
import sqlite3
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ygc.cloud_owner import CloudOwner
from ygc.cloud_owner_routes import owner_router
from ygc.db.postgres_ownership import BoundRepository
from ygc.identity_platform import VerifiedIdentity
from test_acquire_review import setup, submitted, claim, complete


class SQLiteOwnerConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=()):
        if query == 'SELECT * FROM claims WHERE id=? FOR UPDATE':
            query = 'SELECT * FROM claims WHERE id=?'
        return self.connection.execute(query, parameters)


@pytest.fixture
def owner_service(setup, monkeypatch):
    repo, a, b, c, individual = setup
    service = CloudOwner(None, None)

    @contextmanager
    def transaction(actor, requested, *, write=False):
        assert requested == individual
        with repo.connect() as con:
            if write:
                con.execute('BEGIN IMMEDIATE')
            yield BoundRepository(SQLiteOwnerConnection(con)), actor

    monkeypatch.setattr(service, 'transaction', transaction)
    return service


def accepted_acquire(setup):
    repo, *_ = setup
    submitted(setup)
    return complete(repo, claim(repo))['claim_id']


def pending_item(service, owner, individual, claim_id):
    return next(item for item in service.pending(owner, individual)['items'] if item['id'] == str(claim_id))


def assert_unchanged(setup, claim_id, old_revision, service):
    repo, a, b, c, individual = setup
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == a
    item = pending_item(service, a, individual, claim_id)
    assert item['verification_status'] == 'unverified'
    assert item['revision'] == old_revision
    with repo.connect() as con:
        assert not con.execute('SELECT 1 FROM ownership_declines WHERE claim_id=?', (claim_id,)).fetchone()
        assert not con.execute("SELECT 1 FROM notifications WHERE notification_type='ownership_decline' AND claim_id=?", (claim_id,)).fetchone()


def test_owner_acquire_decline_requires_reason_and_saves_atomically(setup, owner_service):
    repo, a, b, c, individual = setup
    claim_id = accepted_acquire(setup)
    item = pending_item(owner_service, a, individual, claim_id)
    assert item['decline_reason_required'] is True
    request = dict(stance='negative', revision=item['revision'])
    with pytest.raises(ValueError, match='reason'):
        owner_service.respond(a, individual, claim_id, request)
    assert_unchanged(setup, claim_id, item['revision'], owner_service)
    result = owner_service.respond(a, individual, claim_id, request | {'reason': '  The guitar is on loan.  '})
    assert result == dict(claim_id=str(claim_id), verification_status='negative')
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == a
    with repo.connect() as con:
        decline = con.execute('SELECT * FROM ownership_declines WHERE claim_id=?', (claim_id,)).fetchone()
        assert decline['owner_id'] == a and decline['reason'] == 'The guitar is on loan.'
        notification = con.execute("SELECT * FROM notifications WHERE notification_type='ownership_decline' AND claim_id=?", (claim_id,)).fetchall()
        assert len(notification) == 1
        assert notification[0]['recipient_user_id'] == b
        assert notification[0]['actor_user_id'] == a
        assert notification[0]['body'] == decline['reason']
        assert con.execute('SELECT verification_status FROM claims WHERE id=?', (claim_id,)).fetchone()[0] == 'negative'


def test_owner_decline_notification_failure_rolls_back_entire_decision(setup, owner_service):
    repo, a, b, c, individual = setup
    claim_id = accepted_acquire(setup)
    item = pending_item(owner_service, a, individual, claim_id)
    with repo.connect() as con:
        con.execute("""CREATE TRIGGER fail_owner_decline BEFORE INSERT ON notifications
            WHEN NEW.notification_type='ownership_decline'
            BEGIN SELECT RAISE(ABORT, 'notification storage failed'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='notification storage failed'):
        owner_service.respond(a, individual, claim_id, dict(stance='negative', revision=item['revision'], reason='On loan'))
    assert_unchanged(setup, claim_id, item['revision'], owner_service)


@pytest.mark.parametrize('reason', [None, True, 7, [], {}, '', '   ', 'x' * 4001])
def test_owner_reason_is_a_bounded_nonempty_string(reason):
    service = CloudOwner(None, None)
    with pytest.raises(ValueError, match='reason'):
        service.respond(1, 1, 1, dict(stance='negative', revision='a' * 64, reason=reason))


@pytest.mark.parametrize('stance', ['positive', 'unverified'])
def test_reason_is_not_silently_accepted_for_other_decisions(stance):
    with pytest.raises(ValueError, match='reason'):
        CloudOwner(None, None).respond(1, 1, 1, dict(stance=stance, revision='a' * 64, reason='Do not silently discard this'))


@pytest.mark.parametrize('kind', ['specification', 'repair'])
def test_owner_pending_has_actual_multifield_content_even_without_body(setup, owner_service, kind):
    repo, a, b, c, individual = setup
    items = [dict(field_name='finish', value_text='<img src=x> Olympic White'), dict(field_name='pickups', value_text='Two single coils')]
    claim_id = repo.create_specification_claim_group(b, individual, specification_kind=kind, items=items, body=None)
    row = pending_item(owner_service, a, individual, claim_id)
    assert row['body'] is None and row['field_name'] is None and row['value_text'] is None
    assert row['specification_kind'] == kind and row['spec_items'] == items
    assert row['decline_reason_required'] is False
    assert owner_service.pending(b, individual)['items'] == []
    owner_service.respond(a, individual, claim_id, dict(stance='negative', revision=row['revision']))


@pytest.mark.parametrize('case', ['too_many', 'long_field', 'long_value', 'missing'])
def test_owner_pending_never_offers_approval_of_truncated_specification(setup, owner_service, case):
    repo, a, b, c, individual = setup
    items = [dict(field_name='finish', value_text='White')]
    if case == 'too_many':
        items = [dict(field_name=f'field_{index}', value_text='value') for index in range(51)]
    if case == 'long_field':
        items[0]['field_name'] = 'f' * 121
    if case == 'long_value':
        items[0]['value_text'] = 'v' * 501
    claim_id = repo.create_specification_claim_group(b, individual, specification_kind='repair', items=items)
    if case == 'missing':
        with repo.connect() as con:
            con.execute('DELETE FROM claim_spec_items WHERE claim_id=?', (claim_id,))
    with pytest.raises(ValueError, match='fully reviewed'):
        owner_service.pending(a, individual)


def test_owner_routes_accept_unicode_reason_at_limit_and_reject_oversized_wire_body(setup, owner_service):
    repo, a, b, c, individual = setup
    claim_id = accepted_acquire(setup)
    item = pending_item(owner_service, a, individual, claim_id)
    verifier = Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': a}
    app = FastAPI()
    app.include_router(owner_router(verifier, owner_service))
    path = f'/api/auth/guitars/{individual}/owner-responses/{claim_id}'
    headers = {'Authorization': 'Bearer fixture', 'Content-Type': 'application/json'}
    reason = '\U0001f3b8' * 4000
    with TestClient(app) as client:
        assert client.post(path, headers=headers, content=' ' * (64 * 1024 + 1)).status_code == 400
        response = client.post(path, headers=headers, content=json.dumps(dict(stance='negative', revision=item['revision'], reason=reason), ensure_ascii=True))
        assert response.status_code == 200, response.text
    with repo.connect() as con:
        assert con.execute('SELECT reason FROM ownership_declines WHERE claim_id=?', (claim_id,)).fetchone()[0] == reason
