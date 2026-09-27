import re
from fastapi.testclient import TestClient
import pytest
from ygc import config
from ygc.db.repository import Repository
from ygc.web import app


def seeded(repo):
    author=repo.create_user('Creator')
    other=repo.create_user('Other')
    individual,_,listing,_=repo.create_initial_listing_claim(
        author,manufacturer='Fender',model='Strat',serial_number='BAN123',
        media_storage_path='media/example.png')
    return author,other,individual,listing


def fields(**changes):
    return dict(display_name='Creator',account_type='user',location_country=None,
                location_region=None,bio=None,birth_visibility='Private',
                residence_visibility='Private',bio_visibility='Public',
                avatar_visibility='Public',signature_individual_id=None,
                ban_status='normal',**changes)


def test_silent_ban_hides_claim_and_snapshot_but_own_claim_appears_active(tmp_path):
    repo=Repository(tmp_path/'test.db');repo.init_db()
    author,other,iid,listing=seeded(repo)
    repo.set_claim_vote(listing,other,'good')
    assert repo.list_claims(iid)[0]['good_count']==1
    payload=fields();payload['ban_status']='silent_ban'
    assert repo.admin_update_user(author,payload)
    assert repo.list_claims(iid)[0]['effective_status']=='inactive'
    assert repo.list_claims(iid,viewer_user_id=author)[0]['effective_status']=='active'
    with repo.connect() as con:
        guitar=con.execute('SELECT manufacturer,serial_number,current_owner_user_id FROM individuals WHERE id=?',(iid,)).fetchone()
        assert guitar['manufacturer']=='Fender' and guitar['serial_number']=='BAN123'
        assert guitar['current_owner_user_id'] is None
        assert con.execute('SELECT status FROM claims WHERE id=?',(listing,)).fetchone()[0]=='active'
    payload['ban_status']='normal'
    repo.admin_update_user(author,payload)
    with repo.connect() as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=?',(iid,)).fetchone()[0]==author
    assert repo.list_claims(iid)[0]['effective_status']=='active'
    assert len(repo.crawl_run_log('electric',1950,1980))==0


def test_ban_hides_account_and_votes_and_rejects_actions(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'test.db')
    repo=Repository(config.DB_PATH);repo.init_db()
    author,other,iid,listing=seeded(repo)
    repo.set_claim_vote(listing,other,'good')
    payload=fields();payload['ban_status']='ban'
    repo.admin_update_user(author,payload)
    assert repo.list_claims(iid,viewer_user_id=author)[0]['effective_status']=='inactive'
    with TestClient(app) as client:
        assert client.get(f'/api/users/{author}/profile?viewer_id={author}').status_code==404
        assert client.get(f'/api/users/{author}').status_code==404
        assert author not in [u['id'] for u in client.get('/api/users').json()]
        assert client.get(f'/api/users/{author}/chronicle').status_code==404
        assert client.get(f'/api/individuals/{iid}/claims?viewer_user_id={other}').json()==[]
        assert client.patch(f'/api/users/{author}',json={'display_name':'Changed'}).status_code==403
        assert client.post(f'/api/claims/{listing}/vote',json={'user_id':author,'vote':'good'}).status_code==404
    payload['ban_status']='normal'
    repo.admin_update_user(author,payload)
    with TestClient(app) as client:
        assert len(client.get(f'/api/individuals/{iid}/claims').json())==1
    # Voter BAN hides their earlier Good without deleting it.
    other_fields=fields();other_fields.update(display_name='Other',ban_status='ban')
    repo.admin_update_user(other,other_fields)
    assert repo.list_claims(iid)[0]['good_count']==0
    other_fields['ban_status']='normal'
    repo.admin_update_user(other,other_fields)
    assert repo.list_claims(iid)[0]['good_count']==1


def test_admin_edit_is_guarded_and_rejects_invalid_signature_atomically(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'test.db')
    repo=Repository(config.DB_PATH);repo.init_db()
    author,other,iid,listing=seeded(repo)
    with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',45000)) as client:
        url=f'/api/admin/users/{author}'
        assert client.patch(url,json=fields()).status_code==403
        token=re.search(r'const CONSOLE_ADMIN_TOKEN="([^"]+)";',client.get('/').text).group(1)
        headers={'X-YGC-Console-Admin':token}
        bad=fields();bad.update(signature_individual_id=999,ban_status='ban')
        assert client.patch(url,json=bad,headers=headers).status_code==400
        assert repo.get_user(author)[0]['ban_status']=='normal'
        good=fields();good.update(display_name='Edited',bio='About me',ban_status='silent_ban',
                                  signature_individual_id=iid)
        assert client.patch(url,json=good,headers=headers).status_code==200
        assert repo.get_user(author)[0]['bio']=='About me'
        assert repo.get_user(author)[0]['ban_status']=='silent_ban'
        assert any(u['id']==author and u['ban_status']=='silent_ban' for u in client.get('/api/users',headers=headers).json())
    with repo.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM user_admin_actions').fetchone()[0]==1


def test_silent_future_claim_and_profile_preview(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'test.db')
    repo=Repository(config.DB_PATH);repo.init_db()
    author,other,iid,listing=seeded(repo)
    settings=fields();settings['ban_status']='silent_ban'
    repo.admin_update_user(author,settings)
    new_id=repo.create_event_claim(author,iid,event_kind='other',detail='Hidden event')
    assert repo.create_claim_notification(new_id) is None
    with TestClient(app) as client:
        assert client.get(f'/api/individuals/{iid}/claims').json()==[]
        mine=client.get(f'/api/individuals/{iid}/claims?viewer_user_id={author}').json()
        assert {c['id'] for c in mine}=={listing,new_id}
        assert all(c['status']=='active' for c in mine)
        public=client.get(f'/api/users/{author}/profile?viewer_id={other}').json()
        own=client.get(f'/api/users/{author}/profile?viewer_id={author}').json()
        assert public['summary']['claim_count']==0
        assert own['summary']['claim_count']==2
        assert public['summary']['owned_count']==0
        assert public['summary']['former_count']==0
        assert public['guitars']==[]
        assert own['summary']['owned_count']==1
        assert client.get(f'/api/individuals/{iid}').status_code==404
        assert client.get(f'/api/individuals/{iid}?viewer_user_id={author}').json()['individual']['current_owner_user_id']==author
    with repo.connect() as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=?',(iid,)).fetchone()[0] is None


def test_existing_db_migrates_ban_default_and_media_is_hidden(tmp_path):
    import sqlite3
    from pathlib import Path
    legacy=tmp_path/'legacy.db'
    schema=(Path(__file__).parents[1]/'src/ygc/db/schema.sql').read_text()
    old_schema=schema.replace(" ban_status TEXT NOT NULL DEFAULT 'normal' CHECK (ban_status IN ('normal','silent_ban','ban')),\n",'')
    with sqlite3.connect(legacy) as connection:
        connection.executescript(old_schema)
    repo=Repository(legacy);repo.init_db()
    author,_,iid,listing=seeded(repo)
    assert repo.get_user(author)[0]['ban_status']=='normal'
    with repo.connect() as con:
        media=con.execute('SELECT id FROM media_assets WHERE individual_id=?',(iid,)).fetchone()[0]
    assert repo.get_media_asset(media) is not None
    payload=fields();payload['ban_status']='silent_ban'
    repo.admin_update_user(author,payload)
    assert repo.get_media_asset(media) is None
    assert repo.get_media_asset(media,viewer_user_id=author) is not None
    payload['ban_status']='ban'
    repo.admin_update_user(author,payload)
    assert repo.get_media_asset(media,viewer_user_id=author) is None
