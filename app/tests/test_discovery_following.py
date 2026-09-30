from fastapi.testclient import TestClient
from ygc import config
from ygc.db.repository import Repository
from ygc.web import app


def test_discovery_uses_current_owner_and_viewers_outgoing_follow(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'discovery.db')
    r = Repository(config.DB_PATH)
    r.init_db()
    a, b, viewer = [r.create_user(name) for name in ('Original owner', 'New owner', 'Viewer')]
    guitar, *_ = r.create_initial_listing_claim(a, manufacturer='Fender', model='Telecaster',
        serial_number='DISC01', media_storage_path='media/test.jpg', occurred_at='2026-01-01')
    r.set_user_follow(a, viewer, True)  # Reverse relationship is not Following.
    with TestClient(app) as client:
        def discovery(who=None):
            suffix = '' if who is None else f'?viewer_id={who}'
            return next(row for row in client.get('/api/new-discoveries'+suffix).json() if row['id']==guitar)
        assert discovery(viewer)['current_owner_following'] is False
        r.set_user_follow(viewer, a, True)
        assert discovery(viewer)['current_owner_following'] is True
        assert discovery()['current_owner_following'] is False
        assert discovery(b)['current_owner_following'] is False
        _, acquire = r.create_ownership_claim(b, guitar, ownership_kind='acquire', occurred_at='2026-02-01')
        pending = discovery(viewer)
        assert pending['current_owner_user_id'] == a
        assert pending['current_owner_following'] is True
        assert r.set_claim_response(acquire, a, 'positive')
        transferred = discovery(viewer)
        assert transferred['current_owner_user_id'] == b
        assert transferred['current_owner_name'] == 'New owner'
        assert transferred['current_owner_following'] is False
        r.set_user_follow(viewer, b, True)
        assert discovery(viewer)['current_owner_following'] is True
        r.set_user_follow(viewer, b, False)
        assert discovery(viewer)['current_owner_following'] is False
        r.create_ownership_claim(b, guitar, ownership_kind='release', occurred_at='2026-03-01')
        unknown = discovery(viewer)
        assert unknown['current_owner_user_id'] is None
        assert unknown['current_owner_name'] is None
        assert unknown['current_owner_following'] is False
