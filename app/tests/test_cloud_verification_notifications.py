"""Owner decisions and their historical author notices commit atomically."""
import sqlite3
from unittest.mock import Mock

import pytest

from test_cloud_claims import services, INCIDENT
from ygc.claim_revision import ClaimConflict
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.postgres_queries import ObservationConnection


def notices(repo, claim=None):
    with repo.connect() as con:
        return [dict(row) for row in con.execute("""SELECT * FROM notifications
            WHERE notification_type='claim_verified' AND (? IS NULL OR claim_id=?) ORDER BY id""",
            (claim, claim))]


@pytest.mark.parametrize('stance', ['positive', 'negative', 'unverified'])
def test_ordinary_decision_notifies_author_once_and_consumes_revision(services, monkeypatch, stance):
    repo, claims, owner, a, b, _, guitar = services
    monkeypatch.setattr('ygc.db.repository.utcnow', lambda: '2020-03-01T00:00:00+00:00')
    row = claims.create(b, guitar, INCIDENT)['claim']
    claim = int(row['id'])
    before = owner.pending(a, guitar)['items'][0]
    payload = dict(stance=stance, revision=before['revision'])
    assert owner.respond(a, guitar, claim, payload) == {'claim_id': str(claim), 'verification_status': stance}
    saved = notices(repo, claim)
    assert len(saved) == 1
    notice = saved[0]
    assert notice['recipient_user_id'] == b and notice['actor_user_id'] == a
    assert notice['individual_id'] == guitar and notice['is_read'] == 0 and notice['read_at'] is None
    assert notice['title'] == 'Claim Verification: ' + stance.title()
    assert notice['body'] == 'Owner set your Claim on Fixture Guitar to ' + stance.title() + '.'
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, claim, payload)
    assert notices(repo, claim) == saved
    after = owner.pending(a, guitar)['items'][0]
    assert after['revision'] != before['revision']
    # Reading the historical notice is not a new decision or a revision change.
    assert repo.mark_notification_read(notice['id'], b)
    assert owner.pending(a, guitar)['items'][0]['revision'] == after['revision']
    owner.respond(a, guitar, claim, dict(stance=stance, revision=after['revision']))
    assert len(notices(repo, claim)) == 2


def test_notification_failure_rolls_back_response_and_snapshot(services):
    repo, claims, owner, a, b, _, guitar = services
    row = claims.create(b, guitar, INCIDENT)['claim']
    before = owner.pending(a, guitar)['items'][0]
    with repo.connect() as con:
        snapshot = dict(con.execute('SELECT * FROM individuals WHERE id=?', (guitar,)).fetchone())
        con.execute("""CREATE TRIGGER fail_verification_notice BEFORE INSERT ON notifications
            WHEN NEW.notification_type='claim_verified' BEGIN SELECT RAISE(ABORT,'fixture failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        owner.respond(a, guitar, int(row['id']), dict(stance='positive', revision=before['revision']))
    assert owner.pending(a, guitar)['items'][0] == before
    assert notices(repo) == []
    with repo.connect() as con:
        assert dict(con.execute('SELECT * FROM individuals WHERE id=?', (guitar,)).fetchone()) == snapshot


def test_stale_or_unauthorized_decision_never_notifies(services):
    repo, claims, owner, a, b, c, guitar = services
    row = claims.create(b, guitar, INCIDENT)['claim']
    claim = int(row['id'])
    payload = dict(stance='positive', revision=owner.pending(a, guitar)['items'][0]['revision'])
    for actor in (b, c):
        with pytest.raises(ValueError):
            owner.respond(actor, guitar, claim, payload)
    claims.edit(b, guitar, claim, INCIDENT | {'body': 'Changed', 'revision': row['revision']})
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, claim, payload)
    assert notices(repo) == []


def test_former_owner_pair_consumes_both_revisions_at_equal_time(services, monkeypatch):
    repo, _, owner, a, b, _, guitar = services
    monkeypatch.setattr('ygc.db.repository.utcnow', lambda: '2020-03-01T00:00:00+00:00')
    pair = repo.create_former_owner_claims(b, guitar, acquisition_date='2018-01-01',
        release_date='2019-01-01', detail='Previous owner')['claim_ids']
    before = {int(row['id']): row for row in owner.pending(a, guitar)['items']}
    owner.respond(a, guitar, pair[0], dict(stance='unverified', revision=before[pair[0]]['revision']))
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, pair[1], dict(stance='unverified', revision=before[pair[1]]['revision']))
    assert len(notices(repo)) == 1


def test_postgres_notice_uses_explicit_returning_without_lastrowid():
    connection = Mock()
    selected, inserted = Mock(), Mock()
    selected.fetchone.return_value = dict(id=7, author_user_id=2, individual_id=4,
        manufacturer='Fender', model='Guitar', verifier_name='Owner')
    inserted.fetchone.return_value = {'id': 9007199254741019}
    connection.execute.side_effect = [selected, inserted]
    repo = BoundRepository(ObservationConnection(connection))
    assert repo.create_verification_notification_in_connection(repo.connection, 7, 1, 'positive') == 9007199254741019
    query, parameters = connection.execute.call_args.args
    assert 'RETURNING id' in query and '%s' in query
    assert parameters[:4] == (2, 1, 4, 7)


def test_transfer_resolution_preserves_earlier_inbox_read_time(services):
    repo, _, _, a, b, _, guitar = services
    claim = repo.create_transfer(a, guitar, b)
    with repo.connect() as con:
        con.execute("UPDATE notifications SET is_read=1,read_at='2020-02-01' WHERE claim_id=?", (claim,))
    repo.resolve_transfer(claim, b, 'decline')
    with repo.connect() as con:
        row = con.execute("SELECT is_read,read_at FROM notifications WHERE claim_id=? AND notification_type='transfer_request'", (claim,)).fetchone()
    assert tuple(row) == (1, '2020-02-01')
