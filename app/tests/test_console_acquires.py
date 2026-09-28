from fastapi.testclient import TestClient

from ygc import config
from ygc.db.repository import Repository
from ygc.web import app


def add_listing(repo, listing_id, serial="524436"):
    return repo.persist_reverb_listing_claim(
        {"manufacturer": "Fender", "model": "Stratocaster", "serial_number": serial,
         "owner_name": "Shop", "source_listing_id": listing_id},
        {"source_site": "reverb", "source_listing_id": listing_id,
         "source_url": f"https://reverb.com/item/{listing_id}",
         "observed_at": "2026-09-27T00:00:00+00:00"},
    )


def test_external_listing_metrics_include_acquire_and_exclude_manual_listing(tmp_path):
    repo = Repository(tmp_path / "db.sqlite")
    repo.init_db()
    owner = repo.create_user("Owner")
    repo.create_initial_listing_claim(owner, manufacturer="Fender", model="Telecaster",
                                      serial_number="MANUAL001", media_storage_path="media/test.jpg")
    first = add_listing(repo, "1")
    second = add_listing(repo, "2")
    assert first["individual_id"] == second["individual_id"]
    assert repo.stats()["individuals"] == 2
    assert repo.stats()["serial_observations"] == 2
    assert repo.stats()["repeated_individuals"] == 0
    add_listing(repo, "2")
    assert repo.stats()["serial_observations"] == 2
    with repo.connect() as con:
        con.execute("UPDATE claims SET status='inactive' WHERE id=?", (second["claim_id"],))
    assert repo.stats()["serial_observations"] == 1
    assert repo.stats()["repeated_individuals"] == 0


def test_pending_acquire_endpoint_total_paging_and_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "db.sqlite")
    repo = Repository(config.DB_PATH)
    repo.init_db()
    owner = repo.create_user("Owner")
    individual_id, _, _, _ = repo.create_initial_listing_claim(
        owner, manufacturer="Fender", model="Stratocaster",
        serial_number="524436", media_storage_path="media/test.jpg",
        occurred_at="2026-09-20")
    first = add_listing(repo, "1")
    second = add_listing(repo, "2")
    assert first["verification_status"] == "unverified"
    with TestClient(app) as client:
        result = client.get('/api/claims/unverified-acquires?limit=1').json()
        assert result["total"] == 2
        assert len(result["items"]) == 1
        assert result["items"][0]["individual_id"] == individual_id
        assert result["items"][0]["current_owner_name"] == "Owner"
        assert result["items"][0]["proposed_owner"] == "Shop"
        next_page = client.get('/api/claims/unverified-acquires?limit=1&offset=1').json()
        assert next_page["items"][0]["claim_id"] != result["items"][0]["claim_id"]
        assert client.get('/api/claims/unverified-acquires?limit=0').status_code == 400
        stats = client.get('/api/status').json()["stats"]
        assert stats["individuals"] == 1
        assert stats["serial_observations"] == 2
        assert stats["repeated_individuals"] == 0
        with repo.connect() as con:
            con.execute("UPDATE claims SET verification_status='positive' WHERE id=?",
                        (first["claim_id"],))
            con.execute("UPDATE claims SET status='inactive' WHERE id=?", (second["claim_id"],))
        assert client.get('/api/claims/unverified-acquires').json()["total"] == 0
