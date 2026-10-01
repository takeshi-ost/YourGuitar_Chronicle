import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient
from ygc import config
from ygc.db.repository import Repository
from ygc.web import app


def test_dm_api_participants_unread_and_claim_independence(tmp_path, monkeypatch):
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'dm.db')
    r=Repository(config.DB_PATH);r.init_db()
    a,b,c=[r.create_user(n) for n in ('A','B','C')]
    guitar,*_=r.create_initial_listing_claim(a,manufacturer='Fender',model='Telecaster',serial_number='DM01',media_storage_path='media/test.jpg')
    def state():
        with r.connect() as con:
            return {t:[tuple(row) for row in con.execute('SELECT * FROM '+t)] for t in ('individuals','claims','claim_evidence','user_guitars','notifications','user_follows')}
    before=state()
    with TestClient(app) as client:
        url=f'/api/dm/users/{b}/messages'
        assert client.get('/api/dm').status_code==401
        assert client.get(url).status_code==401
        assert client.post(url,json={'body':'Hello'}).status_code==401
        assert client.post(url+f'?viewer_id={a}',json={'body':'   '}).status_code==400
        assert client.post(url+f'?viewer_id={a}',json={'body':'x'*2001}).status_code==422
        assert client.post(f'/api/dm/users/{a}/messages?viewer_id={a}',json={'body':'Hello'}).status_code==400
        response=client.post(url+f'?viewer_id={a}',json={'body':'  <script>Hello</script> 日本語\nSecond line  '})
        assert response.status_code==200
        first=response.json()
        assert first['sender_user_id']==a and first['recipient_user_id']==b
        assert first['body']=='<script>Hello</script> 日本語\nSecond line'
        inbox=client.get(f'/api/dm?viewer_id={b}').json()
        assert inbox['unread_count']==1
        assert inbox['conversations'][0]['peer_id']==a
        assert client.get(f'/api/dm?viewer_id={c}').json()['conversations']==[]
        assert client.get(f'/api/dm/users/{a}/messages?viewer_id={c}').json()['messages']==[]
        # A third party cannot read A/B's messages or mark them read.
        assert client.post(f'/api/dm/users/{a}/read?viewer_id={c}',json={'through_id':first['id']}).json()=={'updated':0}
        assert client.get(f'/api/dm?viewer_id={b}').json()['unread_count']==1
        assert client.get(f'/api/dm/users/{a}/messages?viewer_id={b}').json()['messages'][0]['body']==first['body']
        second=r.send_direct_message(a,b,'Later arrival')
        assert client.post(f'/api/dm/users/{a}/read?viewer_id={b}',json={'through_id':first['id']}).json()=={'updated':1}
        assert client.get(f'/api/dm?viewer_id={b}').json()['unread_count']==1
        assert client.post(f'/api/dm/users/{a}/read?viewer_id={b}',json={'through_id':second['id']}).json()=={'updated':1}
        assert client.post(f'/api/dm/users/{a}/read?viewer_id={b}',json={'through_id':second['id']}).json()=={'updated':0}
        assert client.post(f'/api/dm/users/{a}/messages?viewer_id={b}',json={'body':'Reply'}).status_code==200
        assert client.get(f'/api/dm?viewer_id={a}').json()['unread_count']==1
        assert client.get(f'/api/dm/users/9999/messages?viewer_id={a}').status_code==404
        assert state()==before


def test_dm_pagination_and_account_availability(tmp_path):
    r=Repository(tmp_path/'dm.db');r.init_db()
    a,b,c=[r.create_user(n) for n in ('A','B','C')]
    for i in range(6):r.send_direct_message(a,b,str(i))
    r.send_direct_message(c,b,'Other conversation')
    latest=r.direct_message_history(b,a,limit=2)
    assert [m['body'] for m in latest['messages']]==['4','5']
    older=r.direct_message_history(b,a,limit=2,before_id=latest['next_before_id'])
    assert [m['body'] for m in older['messages']]==['2','3']
    oldest=r.direct_message_history(b,a,limit=2,before_id=older['next_before_id'])
    assert [m['body'] for m in oldest['messages']]==['0','1']
    assert oldest['next_before_id'] is None
    inbox=r.direct_message_inbox(b,limit=1)
    assert inbox['conversations'][0]['peer_id']==c
    assert inbox['unread_count']==7
    assert r.direct_message_inbox(b,limit=1,before_id=inbox['next_before_id'])['conversations'][0]['peer_id']==a
    with r.connect() as con:con.execute("UPDATE users SET ban_status='ban' WHERE id=?",(a,))
    assert r.direct_message_inbox(b)['unread_count']==1
    assert len(r.direct_message_inbox(b)['conversations'])==1
    import pytest
    for sender,recipient in ((a,b),(b,a)):
        with pytest.raises(ValueError,match='User not found'):r.send_direct_message(sender,recipient,'Blocked')
    with r.connect() as con:con.execute("UPDATE users SET account_type='source' WHERE id=?",(c,))
    with pytest.raises(ValueError,match='User not found'):r.send_direct_message(b,c,'Blocked')


def test_dm_existing_database_upgrade(tmp_path):
    path=tmp_path/'old.db'
    schema=(Path(__file__).parents[1]/'src/ygc/db/schema.sql').read_text().split('-- Private social messages')[0]
    with sqlite3.connect(path) as con:con.executescript(schema)
    r=Repository(path);r.init_db()
    a,b=[r.create_user(n) for n in ('A','B')]
    r.send_direct_message(a,b,'Persisted')
    r.init_db()
    assert r.direct_message_history(a,b)['messages'][0]['body']=='Persisted'
