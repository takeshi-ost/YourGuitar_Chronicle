from fastapi.testclient import TestClient
import sqlite3
from pathlib import Path

from ygc import config
from ygc.db.repository import Repository
from ygc.theme_catalog import THEMES
from ygc.web import app


def test_curated_themes_persist_and_are_exposed_to_profile_viewers(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "themes.db")
    repo = Repository(config.DB_PATH)
    repo.init_db()
    owner = repo.create_user("Owner")
    viewer = repo.create_user("Viewer")
    assert repo.get_user(owner)[0]["theme"] == "dark_default"
    with TestClient(app) as client:
        stylesheet = client.get("/assets/themes.css")
        assert stylesheet.status_code == 200
        assert 'sunburst_3ply' in stylesheet.text
        assert '/assets/sunburst-wood.webp' in stylesheet.text
        background = client.get("/assets/sunburst-wood.webp")
        assert background.status_code == 200
        assert background.headers['content-type'] == 'image/webp'
        assert background.content.startswith(b'RIFF')
        choices = client.get('/api/themes').json()
        assert [item['id'] for item in choices] == [key for key, _ in THEMES]
        assert len(choices) == 13
        assert next(item['label'] for item in choices if item['id'] == 'sunburst_3ply') == 'Sunburst & White'
        for variant in ('script', 'block', 'badge'):
            logo = client.get(f'/assets/logos/{variant}.svg')
            assert logo.status_code == 200
            assert logo.headers['content-type'].startswith('image/svg+xml')
            assert b'viewBox="0 0 260 56"' in logo.content
        assert client.get('/assets/logos/secret.svg').status_code == 404
        for page in ('/user-view', '/user-view/edit', '/'):
            html = client.get(page).text
            assert 'brand-logo-script' in html and 'brand-logo-block' in html and 'brand-logo-badge' in html
        for key, _ in THEMES[1:]:
            assert f':root[data-theme="{key}"]' in stylesheet.text
        for filename in ('butterscotch-wood.webp', 'cherry-wood.webp', 'white-pearl.webp'):
            asset = client.get('/assets/theme-textures/' + filename)
            assert asset.status_code == 200 and asset.headers['content-type'] == 'image/webp'
        assert client.get('/assets/theme-textures/private.db').status_code == 404
        settings = client.get("/user-view/edit").text
        assert 'id="theme"' in settings
        updated = client.patch(f"/api/users/{owner}", json={
            "display_name": "Owner", "account_type": "user",
            "theme": "sunburst_3ply",
        })
        assert updated.status_code == 200
        assert updated.json()["user"]["theme"] == "sunburst_3ply"
        assert client.get(f"/api/users/{owner}/profile?viewer_id={viewer}").json()["user"]["theme"] == "sunburst_3ply"
        invalid = client.patch(f"/api/users/{owner}", json={
            "display_name": "Owner", "account_type": "user", "theme": "url(unsafe)",
        })
        assert invalid.status_code == 400
    repo.init_db()
    assert repo.get_user(owner)[0]["theme"] == "sunburst_3ply"


def test_new_theme_choices_work_with_existing_three_theme_check(tmp_path):
    path = tmp_path / 'legacy.db'
    schema = (Path(__file__).parents[1] / 'src/ygc/db/schema.sql').read_text()
    schema = schema.replace("theme TEXT NOT NULL DEFAULT 'dark_default',",
                            "theme TEXT NOT NULL DEFAULT 'dark_default' CHECK (theme IN ('dark_default','light_default','sunburst_3ply')),")
    schema = schema.replace(' theme_override TEXT,\n', '')
    with sqlite3.connect(path) as con:
        con.executescript(schema)
    repo = Repository(path)
    repo.init_db()
    user = repo.create_user('Collector')
    for theme, _ in THEMES:
        assert repo.update_user(user,display_name='Collector',account_type='user',
                                location_country=None,location_region=None,theme=theme)
        assert repo.get_user(user)[0]['theme'] == theme
    repo.init_db()
    assert repo.get_user(user)[0]['theme'] == THEMES[-1][0]
    with repo.connect() as con:
        assert con.execute('SELECT theme FROM users WHERE id=?',(user,)).fetchone()[0] == 'dark_default'


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
