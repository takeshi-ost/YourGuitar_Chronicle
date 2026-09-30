from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient
from ygc import config
from ygc.db.repository import Repository
from ygc.web import app


def test_follow_lifecycle_visibility_and_claim_independence(tmp_path, monkeypatch):
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'follows.db')
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    r=Repository(config.DB_PATH);r.init_db()
    a,b,c=[r.create_user(n) for n in ('Owner','Follower','Other')]
    guitar,*_=r.create_initial_listing_claim(a,manufacturer='Fender',model='Telecaster',serial_number='SNS01',media_storage_path='media/test.jpg')
    r.update_user(a,display_name='Owner',account_type='user',location_country='Japan',location_region='Tokyo',bio='Followers bio',date_of_birth='1980-01-02',update_date_of_birth=True,visibility={n:'Followers' for n in ('birth','residence','bio','avatar')})
    (tmp_path/'avatar.png').write_bytes(b'avatar fixture')
    with r.connect() as con:
        con.execute("UPDATE users SET avatar_storage_path='avatar.png',avatar_mime_type='image/png' WHERE id=?",(a,))
    def state():
        with r.connect() as con:
            return {t:[tuple(row) for row in con.execute('SELECT * FROM '+t)] for t in ('individuals','claims','claim_evidence','user_guitars')}
    before=state();permissions={u:r.owner_verifiable_claim_ids(guitar,u) for u in (a,b,c)}
    with TestClient(app) as client:
        url=f'/api/users/{b}/following/{a}'
        profile=lambda viewer:client.get(f'/api/users/{a}/profile?viewer_id={viewer}').json()
        births=lambda:[e for e in client.get(f'/api/users/{a}/chronicle?viewer_id={b}').json() if e['message']=='was born.']
        assert profile(b)['user']['bio'] is None
        assert births()==[]
        assert client.put(url).status_code==401
        assert client.put(url+f'?viewer_id={c}').status_code==403
        assert client.put(f'/api/users/{b}/following/{b}?viewer_id={b}').status_code==400
        for _ in range(2):
            assert client.put(url+f'?viewer_id={b}').json()=={'following':True}
        data=profile(b)
        assert data['social']=={'followers_count':1,'following_count':0,'is_following':True}
        assert data['user']['bio']=='Followers bio'
        assert data['user']['location_region']=='Tokyo'
        assert data['user']['date_of_birth']=='1980-01-02'
        assert data['user']['avatar_visible'] is True
        assert births()[0]['event_at']=='1980-01-02'
        assert client.get(f'/api/users/{a}/avatar?viewer_id={b}').content==b'avatar fixture'
        assert profile(c)['user']['bio'] is None
        assert client.get(f'/api/users/{b}/profile?viewer_id={a}').json()['social']['is_following'] is False
        assert client.get(f'/api/users/{a}/connections/followers').json()==[{'id':b,'display_name':'Follower','account_type':'user'}]
        assert client.get(f'/api/users/{b}/connections/following').json()[0]['id']==a
        assert client.get(f'/api/users/{a}/connections/followers?limit=1&offset=1').json()==[]
        assert client.get(f'/api/users/{a}/connections/followers?limit=101').status_code==422
        assert client.get(f'/api/users/{a}/connections/nope').status_code==400
        assert state()==before
        assert {u:r.owner_verifiable_claim_ids(guitar,u) for u in (a,b,c)}==permissions
        for _ in range(2):
            assert client.delete(url+f'?viewer_id={b}').json()=={'following':False}
        assert profile(b)['user']['bio'] is None
        assert profile(b)['user']['avatar_visible'] is False
        assert births()==[]
        assert client.get(f'/api/users/{a}/avatar?viewer_id={b}').content!=b'avatar fixture'
        assert profile(a)['user']['bio']=='Followers bio'
        assert client.get(f'/api/users/{a}/profile').json()['user']['bio'] is None
        assert state()==before


def test_existing_db_upgrade_and_unavailable_users(tmp_path):
    path=tmp_path/'legacy.db'
    schema=(Path(__file__).parents[1]/'src/ygc/db/schema.sql').read_text().split('-- Social relationships')[0]
    with sqlite3.connect(path) as con:con.executescript(schema)
    r=Repository(path);r.init_db()
    a,b,c=[r.create_user(n) for n in ('A','B','C')]
    r.set_user_follow(b,a,True);r.set_user_follow(c,a,True);r.init_db()
    assert r.user_social_summary(a,b)['followers_count']==2
    with r.connect() as con:
        con.execute("UPDATE users SET ban_status='ban' WHERE id=?",(b,))
        con.execute("UPDATE users SET account_type='source' WHERE id=?",(c,))
    assert r.list_user_connections(a,'followers')==[]
    assert r.user_social_summary(a,b)['followers_count']==0
    assert r.user_social_summary(a,b)['is_following'] is False
    for follower,target in ((b,a),(a,b),(a,c),(a,99999)):
        with pytest.raises(ValueError,match='User not found'):r.set_user_follow(follower,target,True)
