from fastapi.testclient import TestClient

from ygc import config
from ygc.db.repository import Repository
from ygc.web import app


def setup(repo):
    repo.init_db()
    owner = repo.create_user('Owner')
    other = repo.create_user('Other')
    individual, observation, listing, media = repo.create_initial_listing_claim(
        owner, manufacturer='Fender', serial_number='MANUAL-001',
        occurred_at='2026-01-01', media_storage_path='media/manual.jpg',
    )
    assert observation is None
    assert media > 0
    return owner, other, individual, listing


def test_manual_creation_edit_and_pair_verification_never_write_legacy_rows(tmp_path):
    repo = Repository(tmp_path / 'manual.db')
    repo.init_db()
    with repo.connect() as con:
        con.execute("CREATE TRIGGER reject_legacy_insert BEFORE INSERT ON observations "
                    "BEGIN SELECT RAISE(ABORT, 'unexpected legacy write'); END")
        con.execute("CREATE TRIGGER reject_legacy_update BEFORE UPDATE ON observations "
                    "BEGIN SELECT RAISE(ABORT, 'unexpected legacy write'); END")
    owner, other, individual, _ = setup(repo)
    obs, acquire = repo.create_ownership_claim(
        other, individual, ownership_kind='acquire', occurred_at='2026-02-01',
        previous_owner_text=' Shop A ', body='Receipt retained',
    )
    assert obs is None
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == owner
    assert repo.set_claim_response(acquire, owner, 'positive')
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == other
    assert repo.update_claim(acquire, other, occurred_at='2026-02-02', body='Updated note')
    with repo.connect() as con:
        claim = con.execute('SELECT * FROM claims WHERE id=?', (acquire,)).fetchone()
        assert claim['previous_owner_text'] == 'Shop A'
        assert claim['body'] == 'Updated note'
        assert con.execute('SELECT effective_date FROM claim_source_evidence WHERE claim_id=?',
                           (acquire,)).fetchone()[0] == '2026-02-02'
    former = repo.create_user('Former')
    pair = repo.create_former_owner_claims(
        former, individual, acquisition_date='2020-01-01', release_date='2021-01-01',
        detail='Historical ownership',
    )
    assert pair['observation_ids'] == []
    assert len(pair['claim_ids']) == 2
    assert repo.set_claim_response(pair['claim_ids'][0], other, 'positive')
    assert repo.get_user_summary(former)['former_count'] == 1
    obs, release = repo.create_ownership_claim(
        other, individual, ownership_kind='release', occurred_at='2026-03-01',
    )
    assert obs is None and release > 0
    assert repo.get_individual(individual)[0]['current_owner_user_id'] is None
    with repo.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0
        assert con.execute('SELECT COUNT(*) FROM claims WHERE observation_id IS NOT NULL').fetchone()[0] == 0
    assert repo.audit_observation_migration()['individuals_mismatched'] == 0


def test_edit_keeps_existing_legacy_history_unchanged(tmp_path):
    repo = Repository(tmp_path / 'legacy.db')
    owner, other, individual, _ = setup(repo)
    _, acquire = repo.create_ownership_claim(
        other, individual, ownership_kind='acquire', occurred_at='2026-02-01',
    )
    with repo.connect() as con:
        old_id = con.execute(
            "INSERT INTO observations(individual_id,source_site,source_url,observed_at,"
            "occurred_at,created_at,event_type,raw_text) VALUES (?,'user','user://2',"
            "'2026-02-01','2026-02-01','2026-02-01','ownership','Original note')",
            (individual,),
        ).lastrowid
        con.execute('UPDATE claims SET observation_id=? WHERE id=?', (old_id, acquire))
        before = tuple(con.execute('SELECT * FROM observations WHERE id=?', (old_id,)).fetchone())
    assert repo.update_claim(acquire, other, occurred_at='2026-02-03', body='New note')
    assert repo.set_claim_response(acquire, owner, 'positive')
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == other
    repo.init_db()  # Startup must not copy the old date back onto the Claim.
    with repo.connect() as con:
        assert tuple(con.execute('SELECT * FROM observations WHERE id=?', (old_id,)).fetchone()) == before
        assert con.execute('SELECT occurred_at FROM claims WHERE id=?', (acquire,)).fetchone()[0] == '2026-02-03'


def test_acquire_api_requires_review_and_former_owner_avoids_legacy_id(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'api.db')
    repo = Repository(config.DB_PATH)
    owner, other, individual, _ = setup(repo)
    with TestClient(app) as client:
        response = client.post(f'/api/individuals/{individual}/ownership-claim', json={
            'user_id': other, 'ownership_kind': 'acquire', 'occurred_at': '2026-02-01',
            'previous_owner_text': 'Owner',
        })
        assert response.status_code == 409, response.text
        with repo.connect() as con:
            assert con.execute("SELECT COUNT(*) FROM claims WHERE claim_type='ownership'").fetchone()[0] == 0
            assert con.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        response = client.post(f'/api/individuals/{individual}/former-owner-claim', json={
            'user_id': other, 'acquisition_date': '2020-01-01', 'release_date': '2021-01-01',
        })
        assert response.status_code == 200, response.text
        assert 'observation_ids' not in response.json()
        assert len(response.json()['claim_ids']) == 2
