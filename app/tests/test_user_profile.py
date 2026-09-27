from fastapi.testclient import TestClient

from ygc import config
from ygc.db.repository import Repository
from ygc.web import app


def test_profile_uses_top_page_shell_and_activity_is_user_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "chronicle.db")
    repository = Repository(config.DB_PATH)
    repository.init_db()
    owner_id = repository.create_user("Owner")
    other_id = repository.create_user("Other")
    repository.update_user(
        owner_id, display_name="Owner", account_type="user",
        location_country="JP", location_region="Tokyo", bio="My guitars.",
    )
    individual_id, _, listing_claim_id, _ = repository.create_initial_listing_claim(
        owner_id, manufacturer="Fender", model="Telecaster",
        serial_number="PROFILE001", media_storage_path="media/profile.jpg",
    )
    repository.create_event_claim(
        other_id, individual_id, event_kind="exhibition", detail="Exhibited",
    )

    with TestClient(app) as client:
        page = client.get(f"/users/{owner_id}")
        assert page.status_code == 200
        assert 'id="accountHub"' in page.text
        assert 'class="detail-shell"' in page.text
        assert "setupProfileShell" in page.text
        assert client.get(f"/api/users/{owner_id}").json()["user"]["bio"] == "My guitars."

        owner_activity = client.get(f"/api/users/{owner_id}/activity").json()
        other_activity = client.get(f"/api/users/{other_id}/activity").json()
        assert [item["id"] for item in owner_activity] == [listing_claim_id]
        assert len(other_activity) == 1
        assert other_activity[0]["claim_type"] == "event"
        assert client.get("/api/users/999999/activity").status_code == 404
