import re

import pytest
from fastapi.testclient import TestClient

from ygc import config
from ygc.db.repository import Repository, utcnow
from ygc.web import app, CONSOLE_ADMIN_TOKEN


def seed(repo):
    user = repo.create_user("Owner")
    individual, _, claim, _ = repo.create_initial_listing_claim(
        user, manufacturer="Fender", model="Stratocaster", serial_number="524436",
        media_storage_path="media/test.jpg")
    return user, individual, claim


def test_admin_decisions_survive_restart_and_apply_to_all_claim_types(tmp_path):
    repo = Repository(tmp_path / "db.sqlite")
    repo.init_db()
    user, individual, listing = seed(repo)
    ids = [listing]
    with repo.connect() as con:
        for kind in ("ownership", "identity_correction", "specification", "incident", "event", "media"):
            ids.append(con.execute(
                "INSERT INTO claims (individual_id,author_user_id,claim_type,ownership_kind,value_text,created_at,updated_at) "
                "VALUES (?,?,?,'acquire',?,?,?)", (individual,user,kind,str(user),utcnow(),utcnow())
            ).lastrowid)
    for claim in ids:
        for status in ("positive", "unverified", "negative"):
            repo.admin_moderate_claim(claim, status)
            with repo.connect() as con:
                assert con.execute("SELECT verification_status FROM claims WHERE id=?", (claim,)).fetchone()[0] == status
    repo.init_db()
    with repo.connect() as con:
        assert con.execute("SELECT verification_status FROM claims WHERE id=?", (listing,)).fetchone()[0] == 'negative'
        assert con.execute("SELECT current_owner_user_id FROM individuals WHERE id=?", (individual,)).fetchone()[0] is None
        assert con.execute("SELECT COUNT(*) FROM claim_admin_actions").fetchone()[0] == 21
    with pytest.raises(ValueError, match="administrator"):
        repo.set_claim_response(ids[-2], user, "positive")


def test_admin_approve_reject_acquire_rebuilds_owner(tmp_path):
    repo = Repository(tmp_path / "db.sqlite")
    repo.init_db()
    user, individual, _ = seed(repo)
    relisted = repo.persist_reverb_listing_claim(
        {"manufacturer":"Fender", "model":"Stratocaster", "serial_number":"524436", "owner_name":"Shop"},
        {"source_site":"reverb", "source_listing_id":"42", "observed_at":"2090-01-01T00:00:00Z"})
    claim = relisted["claim_id"]
    assert relisted["verification_status"] == 'unverified'
    repo.admin_moderate_claim(claim, 'positive')
    with repo.connect() as con:
        assert con.execute("SELECT current_owner_name FROM individuals WHERE id=?", (individual,)).fetchone()[0] == 'Shop'
    repo.admin_moderate_claim(claim, 'negative')
    with repo.connect() as con:
        assert con.execute("SELECT current_owner_user_id FROM individuals WHERE id=?", (individual,)).fetchone()[0] == user
    repo.admin_moderate_claim(claim, 'delete')
    with repo.connect() as con:
        assert con.execute("SELECT 1 FROM claims WHERE id=?", (claim,)).fetchone() is None


def test_admin_updates_and_deletes_ownership_pair_together(tmp_path):
    repo = Repository(tmp_path / "db.sqlite")
    repo.init_db()
    user, individual, _ = seed(repo)
    paired_at = utcnow()
    with repo.connect() as con:
        ids = []
        for kind, occurred_at in (('acquire', '2020-01-01'), ('release', '2021-01-01')):
            ids.append(con.execute(
                "INSERT INTO claims (individual_id, author_user_id, claim_type, ownership_kind, "
                "ownership_source, ownership_pair_id, value_text, verification_status, occurred_at, created_at, updated_at) "
                "VALUES (?, ?, 'ownership', ?, 'former_owner', 'pair-test', ?, 'unverified', ?, ?, ?)",
                (individual, user, kind, str(user), occurred_at, paired_at, paired_at)).lastrowid)
    repo.admin_moderate_claim(ids[0], 'negative')
    with repo.connect() as con:
        assert [r[0] for r in con.execute("SELECT verification_status FROM claims WHERE ownership_pair_id='pair-test'")] == ['negative', 'negative']
    repo.admin_moderate_claim(ids[1], 'delete')
    with repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM claims WHERE ownership_pair_id='pair-test'").fetchone()[0] == 0


def test_admin_endpoint_requires_local_console_capability_and_explicit_listing_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'db.sqlite')
    repo = Repository(config.DB_PATH)
    repo.init_db()
    _, individual, listing = seed(repo)
    url=f'/api/admin/claims/{listing}/moderate'
    with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 45000)) as client:
        assert client.post(url, json={'action':'negative'}).status_code == 403
        token = re.search(r'const CONSOLE_ADMIN_TOKEN="([^"]+)";', client.get('/').text).group(1)
        headers={'X-YGC-Console-Admin':token}
        assert client.post(url, headers=headers, json={'action':'negative'}).status_code == 200
        assert client.post(url, headers=headers, json={'action':'delete'}).status_code == 409
        assert client.post(url, headers=headers, json={'action':'delete', 'confirm_individual_delete':True}).json()['individual_deleted']
    with TestClient(app, base_url='http://127.0.0.1', client=('203.0.113.1', 45000)) as client:
        assert CONSOLE_ADMIN_TOKEN not in client.get('/').text
        assert client.post(url, headers={'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}, json={'action':'positive'}).status_code == 403
    with repo.connect() as con:
        assert con.execute('SELECT 1 FROM individuals WHERE id=?', (individual,)).fetchone() is None
