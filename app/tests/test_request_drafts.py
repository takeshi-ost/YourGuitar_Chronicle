import time
import pytest
from fastapi.testclient import TestClient
from ygc import acquire_review as ar,listing_review as lr,request_drafts as drafts
from ygc.web import app
from test_acquire_review import setup
from authentication_fixtures import image_bytes


def count(repo):
    with repo.connect() as con:return con.execute('SELECT COUNT(*) FROM acquire_applications').fetchone()[0]


def listing():
    return dict(manufacturer='New Maker',serial_number='NEW123',occurred_at='2026-10-01',body='Saved details')


@pytest.mark.parametrize('kind',['acquire','listing'])
def test_preview_does_not_save_and_keep_preserves_challenge(setup,kind):
    repo,a,b,c,i=setup
    row=ar.start(repo,b,i,preview=True) if kind=='acquire' else lr.start(repo,b,listing(),preview=True)
    assert row['unsaved'] and count(repo)==0
    assert ar.list_for(repo,b)==[]
    assert ar.call_tool(repo,'ygc_pending_'+kind,{})['jobs']==[]
    saved=drafts.keep(repo,b,row['draft_token'])
    assert saved['challenge']==row['challenge'] and saved['revision']==row['revision']
    assert count(repo)==1 and saved['images']=={}
    assert drafts.keep(repo,b,row['draft_token'])['revision']==saved['revision']
    saved=drafts.save_inputs(repo,b,saved['revision'],'2026-10-01','Keep these notes')
    if kind=='acquire':assert saved['body']=='Keep these notes' and saved['acquisition_date']=='2026-10-01'
    ar.action(repo,b,saved['revision'],'cancel')
    assert ar.list_for(repo,b)[0]['status']=='cancelled'
    with pytest.raises(ValueError):drafts.keep(repo,b,row['draft_token'])


def test_preview_tokens_reject_tampering_other_users_expiry_and_restart(setup,monkeypatch):
    repo,a,b,c,i=setup;row=ar.start(repo,b,i,preview=True);token=row['draft_token']
    for invalid,user in [(token+'x',b),(token,c)]:
        with pytest.raises(ValueError):drafts.keep(repo,user,invalid)
    monkeypatch.setattr(drafts.time,'time',lambda:row['expires_at']+1)
    with pytest.raises(ValueError):drafts.keep(repo,b,token)
    assert count(repo)==0


@pytest.mark.parametrize('kind',['acquire','listing'])
def test_http_submit_creates_request_only_with_valid_photos(setup,kind):
    repo,a,b,c,i=setup;client=TestClient(app)
    url=f'/api/ownership-drafts/acquire/{i}' if kind=='acquire' else '/api/ownership-drafts/listing'
    response=client.post(url+'?viewer_id='+str(b),json=listing() if kind=='listing' else None)
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    row=response.json();assert count(repo)==0
    data=dict(draft_token=row['draft_token'],acquisition_date='2026-10-01',body='Text')
    target='/api/ownership-drafts/submit?viewer_id='+str(b)
    assert client.post(target,data=data,files={'closeup':('bad.jpg',b'bad','image/jpeg'),'overview':('ok.png',image_bytes(),'image/png')}).status_code==409
    assert count(repo)==0
    done=client.post(target,data=data,files={role:('photo.png',image_bytes(),'image/png') for role in ('closeup','overview')})
    assert done.status_code==200,done.text
    assert done.json()['status']=='pending' and count(repo)==1
    assert done.json()['challenge']==row['challenge']


def test_keep_http_saves_inputs_without_photos_and_checks_actor(setup):
    repo,a,b,c,i=setup;client=TestClient(app);row=ar.start(repo,b,i,preview=True)
    payload=dict(draft_token=row['draft_token'],acquisition_date='2026-10-01',body='Receipt')
    assert client.post('/api/ownership-drafts/keep?viewer_id='+str(c),json=payload).status_code==409
    assert count(repo)==0
    response=client.post('/api/ownership-drafts/keep?viewer_id='+str(b),json=payload)
    assert response.status_code==200 and response.json()['body']=='Receipt' and response.json()['images']=={}
    assert client.post('/api/ownership-drafts/keep?viewer_id='+str(c),json=dict(revision=row['revision'],body='overwrite')).status_code==403
