from fastapi.testclient import TestClient

from ygc import config
from ygc.db.repository import Repository
from ygc.web import app


def test_favorites_toggle_and_profile_excludes_owned_guitars(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "favorites.db")
    repository = Repository(config.DB_PATH)
    repository.init_db()
    owner = repository.create_user("Owner")
    viewer = repository.create_user("Viewer")
    owned, *_ = repository.create_initial_listing_claim(
        owner, manufacturer="Fender", model="Mustang",
        serial_number="FAVOWN01", media_storage_path="media/owned.jpg",
    )
    other, *_ = repository.create_initial_listing_claim(
        viewer, manufacturer="Gibson", model="SG",
        serial_number="FAVOTHER01", media_storage_path="media/other.jpg",
    )
    with TestClient(app) as client:
        for guitar in (owned, other):
            assert client.put(f"/api/users/{owner}/favorites/{guitar}").json() == {"favorite": True}
        assert set(client.get(f"/api/users/{owner}/favorites").json()) == {owned, other}
        profile = client.get(f"/api/users/{owner}/profile?viewer_id={viewer}").json()
        assert [g["individual_id"] for g in profile["favorites"]] == [other]
        assert [g["individual_id"] for g in profile["guitars"]] == [owned]
        assert client.delete(f"/api/users/{owner}/favorites/{other}").json() == {"favorite": False}
        assert client.get(f"/api/users/{owner}/profile?viewer_id={viewer}").json()["favorites"] == []
        assert client.put(f"/api/users/{owner}/favorites/999999").status_code == 404
    repository.init_db()
    assert [g["individual_id"] for g in repository.get_user_favorites(owner)] == [owned]


def test_profile_uses_top_page_shell_and_chronicle_is_user_scoped(tmp_path, monkeypatch):
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
    event_claim_id = repository.create_event_claim(
        other_id, individual_id, event_kind="exhibition", detail="Exhibited",
    )
    assert repository.set_claim_vote(event_claim_id, owner_id, "good")

    with TestClient(app) as client:
        page = client.get(f"/users/{owner_id}")
        assert page.status_code == 200
        assert 'id="accountHub"' in page.text
        assert 'class="detail-shell"' in page.text
        assert "setupProfileShell" in page.text
        assert client.get(f"/api/users/{owner_id}").json()["user"]["bio"] == "My guitars."

        owner_entries = client.get(f"/api/users/{owner_id}/chronicle").json()
        other_entries = client.get(f"/api/users/{other_id}/chronicle").json()
        assert {item["category"] for item in owner_entries} == {
            "User", "Product", "Claim", "Social",
        }
        assert any(item["category"] == "Claim" and "Listing" in item["message"]
                   for item in owner_entries)
        assert any(item["category"] == "Social" and "Good vote" in item["message"]
                   for item in owner_entries)
        assert [item["event_at"] for item in owner_entries] == sorted(
            (item["event_at"] for item in owner_entries), reverse=True,
        )
        assert all(item["category"] != "Social" for item in other_entries)
        assert any(item["category"] == "Claim" and "Exhibition" in item["message"]
                   for item in other_entries)
        assert client.get("/api/users/999999/chronicle").status_code == 404


def test_user_settings_layout_and_extended_account_types(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "chronicle.db")
    repository = Repository(config.DB_PATH)
    repository.init_db()
    user_id = repository.create_user("Builder")
    with TestClient(app) as client:
        page = client.get("/user-view/edit")
        assert page.status_code == 200
        assert '<h2 id="profileHeading">User Profile</h2>' in page.text
        assert 'id="newGuitarModal"' in page.text
        assert 'Product Detail' not in page.text
        assert 'data-field="residence"' in page.text
        assert 'type="email"' in page.text
        response = client.patch(f"/api/users/{user_id}", json={
            "display_name": "Builder", "account_type": "builder",
            "location_country": "JP", "location_region": "Tokyo",
        })
        assert response.status_code == 200
        assert response.json()["user"]["account_type"] == "builder"


def test_profile_visibility_and_signature_guitar(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "chronicle.db")
    repository = Repository(config.DB_PATH)
    repository.init_db()
    owner = repository.create_user("Owner")
    viewer = repository.create_user("Viewer")
    guitar, *_ = repository.create_initial_listing_claim(
        owner, manufacturer="Fender", model="Mustang",
        serial_number="SIGNATURE01", media_storage_path="media/test.jpg",
    )
    with TestClient(app) as client:
        response = client.patch(f"/api/users/{owner}", json={
            "display_name": "Owner", "account_type": "user",
            "location_country": "JP", "location_region": "Tokyo",
            "bio": "Private bio", "residence_visibility": "Followers",
            "bio_visibility": "Private", "avatar_visibility": "Members",
            "signature_individual_id": guitar,
        })
        assert response.status_code == 200
        other = client.get(f"/api/users/{owner}/profile?viewer_id={viewer}").json()["user"]
        assert other["location_country"] is None
        assert other["bio"] is None
        assert other["avatar_visible"] is True
        assert other["signature_individual_id"] == guitar
        own = client.get(f"/api/users/{owner}/profile?viewer_id={owner}").json()["user"]
        assert own["location_country"] == "JP"
        assert own["bio"] == "Private bio"
        assert client.get(f"/api/users/{owner}/profile").json()["user"]["avatar_visible"] is False
        invalid = client.patch(f"/api/users/{viewer}", json={
            "display_name": "Viewer", "account_type": "user",
            "signature_individual_id": guitar,
        })
        assert invalid.status_code == 400
