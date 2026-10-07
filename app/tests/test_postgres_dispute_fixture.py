"""Portable checks for PG dispute fixture semantics; no PostgreSQL or sockets."""
from contextlib import contextmanager

import pytest

import postgres_dispute_checks as acceptance
from ygc import disputes
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.postgres_queries import ObservationConnection
from ygc.db.repository import Repository


class FixtureConnection:
    """Run the fixture's parameterized, portable SQL on a disposable SQLite DB."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=()):
        return self.connection.execute(query.replace('%s', '?'), parameters)


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    repo = Repository(tmp_path / 'dispute-fixture.db')
    repo.init_db()
    records = {name: {'id': repo.create_user('Synthetic ' + name),
                      'app_user_id': 'synthetic-' + name}
               for name in ('a', 'b', 'c', 'admin')}

    @contextmanager
    def connect(settings, target):
        assert target == 'chronicle'
        with repo.connect() as con:
            yield FixtureConnection(con)

    monkeypatch.setattr(acceptance, 'connect', connect)
    return repo, acceptance.Workflow(None, None, records, None)


def relations(repo, guitar):
    with repo.connect() as con:
        return {row['user_id']: row['ownership_status'] for row in con.execute(
            'SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=?', (guitar,))}


@pytest.mark.parametrize('action', ['owner', 'applicant'])
def test_listing_fixture_and_dispute_decisions_materialize_only_accepted_owners(workflow, action):
    repo, w = workflow
    guitar = w.guitar()
    w.current(guitar, 'a')
    assert relations(repo, guitar) == {w.user('a'): 'current_owner'}

    claim = w.acquire(guitar=guitar)
    # Image-review acceptance creates an Unverified Acquire, not an Owned or
    # Formerly Owned profile entry. Mere dispute opening cannot create one.
    assert relations(repo, guitar) == {w.user('a'): 'current_owner'}
    with repo.connect() as con:
        case = disputes.open_case(con, claim, w.user('b'), 'Synthetic explanation',
            'Synthetic summary', acceptance.PDF, 'application/pdf', 'document.pdf')
    w.current(guitar, 'a')
    assert relations(repo, guitar) == {w.user('a'): 'current_owner'}

    with repo.connect() as con:
        version = disputes.get_case(con, case, admin=True)['version']
        disputes.decide(repo, con, case, version, action, 'Synthetic reviewed decision',
                        claim if action == 'applicant' else None)
    if action == 'owner':
        w.current(guitar, 'a')
        assert relations(repo, guitar) == {w.user('a'): 'current_owner'}
    else:
        w.current(guitar, 'b', former=('a',))
        assert relations(repo, guitar) == {
            w.user('a'): 'former_owner', w.user('b'): 'current_owner'}
        # Keep the acceptance helper strict about missing former-owner links.
        with repo.connect() as con:
            con.execute('DELETE FROM user_guitars WHERE user_id=? AND individual_id=?',
                        (w.user('a'), guitar))
        with pytest.raises(AssertionError):
            w.current(guitar, 'b', former=('a',))


def test_ownerless_fixture_gains_profile_link_only_when_basis_acquire_is_approved(workflow):
    repo, w = workflow
    guitar = w.guitar(owner=None)
    basis = w.acquire('a', guitar=guitar, occurred='2026-02-01')
    with repo.connect() as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=?',
                           (guitar,)).fetchone()['current_owner_user_id'] is None
    assert relations(repo, guitar) == {}

    # Match locked_owner_ban_projection_checks' fixture approval. Normal Admin
    # moderation records the accepted Acquire before evaluating the snapshot.
    with acceptance.connect(w.db_owner, 'chronicle') as raw:
        bound = BoundRepository(ObservationConnection(raw))
        bound.admin_moderate_claim_in_connection(bound.connection, basis, 'positive')
    w.current(guitar, 'a')
    assert relations(repo, guitar) == {w.user('a'): 'current_owner'}

    # A correct snapshot alone cannot satisfy the profile-link assertion.
    with repo.connect() as con:
        con.execute('DELETE FROM user_guitars WHERE individual_id=?', (guitar,))
    with pytest.raises(AssertionError):
        w.current(guitar, 'a')
