from fastapi.testclient import TestClient
from ygc import config
from ygc.db.repository import Repository
from ygc.web import app


def test_discovery_mixes_followed_actor_actions_with_global_news(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'discovery.db')
    r = Repository(config.DB_PATH)
    r.init_db()
    owner, actor, viewer, other = [r.create_user(n) for n in ('Owner','Actor','Viewer','Other')]
    guitar, *_, listing = r.create_initial_listing_claim(owner, manufacturer='Fender', model='Telecaster',
        serial_number='DISC01', media_storage_path='media/test.jpg', occurred_at='2026-01-01')
    extra, *_ = r.create_initial_listing_claim(other, manufacturer='Gibson', model='SG',
        serial_number='DISC02', media_storage_path='media/test2.jpg')
    claim = r.create_specification_claim_group(actor, guitar, specification_kind='specification',
        items=[{'field_name':'finish','value_text':'Black'}], occurred_at='2020-01-01')
    r.set_user_follow(actor, viewer, True)  # Reverse Follow is not a subscription.
    with TestClient(app) as client:
        def rows(who=None):
            suffix='' if who is None else f'?viewer_id={who}'
            return client.get('/api/new-discoveries'+suffix).json()
        assert not any(x['activity_type']=='following' for x in rows(viewer))
        r.set_user_follow(viewer, owner, True)
        assert not any(x.get('claim_id')==claim for x in rows(viewer))  # Owner follow does not select actor.
        r.set_user_follow(viewer, actor, True)
        data=rows(viewer)
        action=next(x for x in data if x.get('claim_id')==claim)
        assert action['activity_type']=='following'
        assert action['actor_user_id']==actor
        assert action['actor_name']=='Actor'
        assert action['id']==guitar
        assert action['activity_at']==next(c for c in r.list_claims(guitar) if c['id']==claim)['created_at']
        assert any(x['id']==extra and x['activity_type']!='following' for x in data)
        assert sum(x.get('claim_id')==claim or x.get('latest_claim_id')==claim for x in data)==1
        # An older followed action must remain even when an unrelated user makes a newer Claim.
        r.create_event_claim(other,guitar,event_kind='performance',occurred_at='2026-03-01',detail='Played')
        assert any(x.get('claim_id')==claim for x in rows(viewer))
        assert any(x['id']==guitar and x['activity_type']=='claim' for x in rows(viewer))
        r.set_claim_vote(claim,actor,'good')
        assert any(x.get('action_kind')=='vote' and x['actor_user_id']==actor for x in rows(viewer))
        assert not any(x['activity_type']=='following' for x in rows())
        assert not any(x['activity_type']=='following' for x in rows(other))
        r.set_user_follow(viewer,actor,False)
        assert not any(x.get('actor_user_id')==actor for x in rows(viewer))
        r.set_user_follow(viewer,actor,True)
        with r.connect() as con:
            con.execute("UPDATE users SET ban_status='silent_ban' WHERE id=?",(actor,))
        assert not any(x.get('actor_user_id')==actor for x in rows(viewer))
