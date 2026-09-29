import pytest

from ygc.db.repository import utcnow


@pytest.fixture
def legacy_marketplace_row():
    """Explicitly model a pre-Evidence writer without using today's write path."""
    def attach(repo, result, claim, provenance):
        observation_id, created = repo.upsert_observation({
            **claim, **provenance, 'individual_id': result['individual_id'],
            'observed_at': provenance.get('observed_at') or utcnow(),
            'created_at': provenance.get('created_at') or utcnow(),
        })
        assert created
        with repo.connect() as con:
            con.execute('UPDATE claims SET observation_id=? WHERE id=?',
                        (observation_id, result['claim_id']))
            con.execute('UPDATE claim_source_evidence SET legacy_observation_id=? WHERE claim_id=?',
                        (observation_id, result['claim_id']))
        return observation_id
    return attach
