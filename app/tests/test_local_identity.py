import sqlite3
import zipfile
import pytest
from fastapi.testclient import TestClient
from ygc import config, web, accounts, crawl_backups, operations
from ygc.db.repository import Repository
from ygc.platform_boundaries import LocalDummyIdentity, PlatformAdapterRequired, require_local_platform


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('YGC_IDENTITY_BACKEND','local_dummy')
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'chronicle.db')
    monkeypatch.setattr(config,'ACCOUNTS_DB_PATH',tmp_path/'accounts.sqlite')
    monkeypatch.setattr(web,'MEDIA_DIR',tmp_path/'media')
    monkeypatch.setattr(web,'_jobs',{})
    monkeypatch.setattr(web,'_active_job_id',None)
    r=web.repo();r.init_db()
    return r


def client():
    return TestClient(web.app,base_url='http://127.0.0.1',client=('127.0.0.1',45000))


ADMIN={'X-YGC-Console-Admin':web.CONSOLE_ADMIN_TOKEN}


def test_legacy_migration_uuid_stability_and_sessions(setup):
    import uuid
    a=setup.create_user('A');b=setup.create_user('B')
    session=accounts.login(setup,a,now=100)
    assert uuid.UUID(session['app_user_id']).version == 4
    adapter=LocalDummyIdentity(setup)
    principal=accounts.resolve_session(setup,session['token'],now=101)
    assert principal['id']==a and principal['app_user_id']==session['app_user_id']
    with pytest.raises(PermissionError):accounts.resolve_session(setup,session['token'],now=3700)
    live=accounts.login(setup,a)
    assert adapter.resolve(bearer_token=live['token']).app_user_id==session['app_user_id']
    with pytest.raises(PermissionError):adapter.resolve(bearer_token=live['token'],prototype_user_id=b)
    setup.init_db()
    assert setup.get_user(a)[0]['app_user_id']==session['app_user_id']
    accounts.logout(setup,live['token'])
    with pytest.raises(PermissionError):adapter.resolve(bearer_token=live['token'])


def test_dummy_guard_impersonation_multipart_and_privacy(setup):
    a=setup.create_user('A');b=setup.create_user('B')
    with client() as c:
        token=c.post('/api/local-auth/login',json={'user_id':a}).json()['token']
        headers={'Authorization':'Bearer '+token}
        assert c.get(f'/api/users/{a}',headers=headers).status_code==200
        assert c.get(f'/api/users/{b}',headers=headers).status_code==403
        assert c.get(f'/api/users/{a}').status_code==403
        assert set(c.get('/api/users').json()[0])=={'id','display_name','account_type','theme'}
        assert c.patch(f'/api/users/{b}',headers=headers,json={'display_name':'Forged'}).status_code==403
        assert c.post('/api/individuals/1/event-claim',headers=headers,json={'user_id':b,'event_kind':'repair','detail':'Forged'}).status_code==403
        assert c.post('/api/individuals/1/media-claim',headers=headers,data={'user_id':b},files={'file':('x.jpg',b'x','image/jpeg')}).status_code==403
        # The cached multipart body still reaches the intended endpoint.
        response=c.post(f'/api/users/{a}/avatar',headers=headers,files={'avatar':('x.jpg',b'avatar','image/jpeg')})
        assert response.status_code==200,response.text
        assert c.get(f'/api/users/{a}/avatar?viewer_id={a}',headers=headers).content==b'avatar'
        assert c.post('/api/local-auth/login',headers={'Origin':'http://evil.example'},json={'user_id':a}).status_code==403
        with setup.connect() as con:con.execute('UPDATE account_records SET disabled=1 WHERE id=?',(a,))
        assert c.get(f'/api/users/{a}',headers=headers).status_code==401
        assert c.post('/api/local-auth/login',json={'user_id':a}).status_code==403


def test_content_restore_preserves_accounts_social_ban_and_avatar(setup):
    a=setup.create_user('A');b=setup.create_user('B')
    old=crawl_backups.create(web.api_export_db)
    later=setup.create_user('Later')
    setup.set_user_follow(a,b,True)
    message=setup.send_direct_message(a,b,'Keep this message')
    with client() as c:
        token=c.post('/api/local-auth/login',json={'user_id':a}).json()['token']
        assert c.post(f'/api/users/{a}/avatar',headers={'Authorization':'Bearer '+token},files={'avatar':('x.jpg',b'latest-avatar','image/jpeg')}).status_code==200
        with setup.connect() as con:
            con.execute("UPDATE users SET display_name='Latest',ban_status='silent_ban' WHERE id=?",(a,))
            con.execute("UPDATE account_records SET role='admin' WHERE id=?",(a,))
        operations.update('read_only','','test',operations.state()['version'])
        response=c.post('/api/admin/operations/backups/'+old+'/restore',headers=ADMIN)
        assert response.status_code==200,response.text
        assert setup.get_user(later)[0]['display_name']=='Later'
        user=setup.get_user(a)[0]
        assert user['display_name']=='Latest' and user['ban_status']=='silent_ban'
        assert (config.DATA_DIR/user['avatar_storage_path']).read_bytes()==b'latest-avatar'
        assert setup.direct_message_history(a,b)['messages'][0]['id']==message['id']
        assert setup.user_social_summary(a,b)['following_count']==1
        assert accounts.resolve_session(setup,token)['role']=='admin'
        assert setup.create_user('Next')>later


def test_account_backup_restores_only_accounts_and_reserves_new_ids(setup):
    a=setup.create_user('A')
    session=accounts.login(setup,a)
    saved=crawl_backups.create(web.api_export_db,'accounts','manual')
    with zipfile.ZipFile(crawl_backups.selected(saved)) as z:
        snapshot=config.DATA_DIR/'snapshot.sqlite';snapshot.write_bytes(z.read('database.sqlite'))
    with sqlite3.connect(snapshot) as con:assert con.execute('SELECT COUNT(*) FROM local_sessions').fetchone()[0]==0
    later=setup.create_user('Later')
    with setup.connect() as con:con.execute("UPDATE users SET display_name='Changed' WHERE id=?",(a,))
    before=setup.stats()
    operations.update('read_only','','test',operations.state()['version'])
    with client() as c:
        response=c.post('/api/admin/operations/backups/'+saved+'/restore',headers=ADMIN)
        assert response.status_code==200,response.text
    assert setup.get_user(a)[0]['display_name']=='A'
    assert setup.stats()['individuals']==before['individuals']
    with pytest.raises(PermissionError):accounts.resolve_session(setup,session['token'])
    with pytest.raises(PermissionError):accounts.login(setup,later)
    assert setup.create_user('Next')>later


def test_cloud_refuses_dummy_before_data_access(setup,monkeypatch):
    monkeypatch.setenv('K_SERVICE','production')
    with pytest.raises(PlatformAdapterRequired):require_local_platform()


def test_guitar_reset_preserves_account_registry(setup):
    a=setup.create_user('A')
    identity=setup.get_user(a)[0]['app_user_id']
    with client() as c:
        response=c.post('/api/reset-db',headers=ADMIN,json={'confirm':'RESET'})
        assert response.status_code==200,response.text
    assert setup.get_user(a)[0]['app_user_id']==identity


def test_ownership_transition_with_authenticated_callers(setup):
    a=setup.create_user('A');b=setup.create_user('B')
    individual,_,listing,_=setup.create_initial_listing_claim(a,manufacturer='Fender',model='Telecaster',serial_number='DUMMY-001',media_storage_path='media/test.jpg',occurred_at='2020-01-01')
    _,claim=setup.create_ownership_claim(b,individual,ownership_kind='acquire',occurred_at='2021-01-01')
    assert setup.get_individual(individual)[0]['current_owner_user_id']==a
    assert not setup.get_user(b)[1]
    with client() as c:
        ha={'Authorization':'Bearer '+c.post('/api/local-auth/login',json={'user_id':a}).json()['token']}
        hb={'Authorization':'Bearer '+c.post('/api/local-auth/login',json={'user_id':b}).json()['token']}
        def verify(claim_id,user,headers,status='positive'):
            return c.post(f'/api/claims/{claim_id}/response',headers=headers,json={'responder_user_id':user,'stance':status})
        assert verify(claim,b,hb).status_code==400
        assert verify(claim,a,hb).status_code==403
        assert verify(claim,a,ha).status_code==200
        assert setup.get_individual(individual)[0]['current_owner_user_id']==b
        assert setup.get_user(a)[1][0]['ownership_status']=='former_owner'
        assert setup.get_user(b)[1][0]['ownership_status']=='current_owner'
        assert verify(claim,b,hb,'negative').status_code==400
        _,return_claim=setup.create_ownership_claim(a,individual,ownership_kind='acquire',occurred_at='2022-01-01')
        assert verify(return_claim,a,ha).status_code==400
        assert verify(return_claim,b,hb).status_code==200
        assert setup.get_individual(individual)[0]['current_owner_user_id']==a
        assert c.post(f'/api/admin/claims/{return_claim}/moderate',headers=ha,json={'action':'negative'}).status_code==403
        assert c.post(f'/api/admin/claims/{return_claim}/moderate',headers=ADMIN,json={'action':'negative'}).status_code==200
        assert setup.get_individual(individual)[0]['current_owner_user_id']==b
        assert setup.observation_diagnostic(individual)['differences']=={}


def test_legacy_account_migration_and_identity_conflict(tmp_path):
    db=tmp_path/'chronicle.db';path=tmp_path/'accounts.sqlite'
    old=Repository(db);old.init_db();a=old.create_user('Original')
    root=tmp_path/'media'/'users';root.mkdir(parents=True);(root/'old.jpg').write_bytes(b'old-avatar')
    old.update_user_avatar(a,storage_path='media/users/old.jpg',original_filename='old.jpg',mime_type='image/jpeg')
    new=Repository(db,account_db_path=path);new.init_db()
    assert list(tmp_path.glob('before_account_split_*.sqlite'))
    assert (tmp_path/new.get_user(a)[0]['avatar_storage_path']).read_bytes()==b'old-avatar'
    with new.connect() as con:
        with pytest.raises(sqlite3.IntegrityError):con.execute("UPDATE users SET app_user_id='forged' WHERE id=?",(a,))
    # A foreign DB cannot overwrite the same numeric ID with a different identity.
    with sqlite3.connect(db) as con:con.execute("UPDATE users SET app_user_id='foreign' WHERE id=?",(a,))
    with pytest.raises(ValueError,match='identity conflict'):new.get_user(a)


def test_account_restore_avatar_and_conflicting_identity_rejection(setup):
    import io
    a=setup.create_user('A')
    with client() as c:
        token=c.post('/api/local-auth/login',json={'user_id':a}).json()['token']
        h={'Authorization':'Bearer '+token}
        assert c.post(f'/api/users/{a}/avatar',headers=h,files={'avatar':('old.jpg',b'old','image/jpeg')}).status_code==200
        name=crawl_backups.create(web.api_export_db,'accounts','manual')
        assert c.post(f'/api/users/{a}/avatar',headers=h,files={'avatar':('new.jpg',b'new','image/jpeg')}).status_code==200
        operations.update('read_only','','test',operations.state()['version'])
        assert c.post('/api/admin/operations/backups/'+name+'/restore',headers=ADMIN).status_code==200
        assert (config.DATA_DIR/setup.get_user(a)[0]['avatar_storage_path']).read_bytes()==b'old'
    # A mismatched UUID under the same integer ID is rejected without replacing live data.
    with zipfile.ZipFile(crawl_backups.selected(name)) as z:
        data={n:z.read(n) for n in z.namelist()}
    candidate=config.DATA_DIR/'foreign.sqlite';candidate.write_bytes(data['database.sqlite'])
    with sqlite3.connect(candidate) as con:
        con.execute('DROP TRIGGER immutable_account_identity')
        con.execute("UPDATE account_records SET app_user_id='foreign' WHERE id=?",(a,))
        con.execute("UPDATE identity_links SET app_user_id='foreign'")
    data['database.sqlite']=candidate.read_bytes()
    payload=io.BytesIO()
    with zipfile.ZipFile(payload,'w') as z:
        for n,value in data.items():z.writestr(n,value)
    original=setup.get_user(a)[0]['app_user_id']
    with pytest.raises(ValueError,match='reassign'):crawl_backups.restore_auxiliary(payload.getvalue(),'accounts')
    assert setup.get_user(a)[0]['app_user_id']==original


def test_web_entrypoint_selects_dummy_and_split_cannot_fall_back(setup,monkeypatch):
    import sys
    monkeypatch.delenv('YGC_IDENTITY_BACKEND')
    monkeypatch.setattr(sys,'argv',['ygc-web','--no-browser'])
    monkeypatch.setattr(web.uvicorn,'run',lambda *args,**kwargs:None)
    web.main()
    from ygc.local_identity import enabled
    assert enabled()
    monkeypatch.setenv('YGC_IDENTITY_BACKEND','prototype')
    with pytest.raises(PlatformAdapterRequired,match='split accounts'):web.repo()


def test_sign_in_result_contract_and_stable_dummy_identity(setup):
    with client() as c:
        first=c.post('/api/local-auth/sign-in',json={})
        assert first.status_code==200,first.text
        result=first.json()
        assert result['idToken']==result['token']
        assert result['localId']==result['subject']
        assert result['expiresIn']=='3600'
        assert result['refreshToken'] is None and not result['capabilities']['refresh']
        assert result['registered'] is True
        assert accounts.resolve_session(setup,result['idToken'])['id']==result['user_id']
        again=c.post('/api/local-auth/sign-in',json={}).json()
        assert again['localId']==result['localId'] and again['idToken']!=result['idToken']
        assert len(setup.list_users())==1
        assert c.post('/api/local-auth/sign-in',headers={'Origin':'http://evil.example'},json={}).status_code==403
        assert c.post('/api/local-auth/logout',headers={'Authorization':'Bearer '+result['idToken']}).status_code==200
        with pytest.raises(PermissionError):accounts.resolve_session(setup,result['idToken'])


def test_sign_in_user_hint_and_disabled_fallback(setup):
    a=setup.create_user('Registered Test User')
    with client() as c:
        assert c.post('/api/local-auth/sign-in',json={'user_id':a}).json()['user_id']==a
        with setup.connect() as con:con.execute('UPDATE account_records SET disabled=1 WHERE id=?',(a,))
        assert c.post('/api/local-auth/sign-in',json={'user_id':a}).status_code==403
        result=c.post('/api/local-auth/sign-in',json={}).json()
        assert result['user_id']!=a
        assert accounts.resolve_session(setup,result['idToken'])['disabled']==0


def test_registration_requires_profile_consent_and_preserves_credentials_boundary(setup):
    from ygc.registration import VERSION
    payload={'display_name':'  Nick  ','terms_accepted':True,'privacy_accepted':True,'terms_version':VERSION,'privacy_version':VERSION}
    with client() as c:
        for bad in ({**payload,'display_name':' '},{**payload,'terms_accepted':False},{**payload,'privacy_version':'old'},{**payload,'password':'secret'},{**payload,'account_type':'admin'}):
            assert c.post('/api/local-auth/register',json=bad).status_code==400
        assert c.post('/api/users').status_code==403
        first=c.post('/api/local-auth/register',json=payload)
        second=c.post('/api/local-auth/register',json={**payload,'account_type':'shop'})
        assert first.status_code==second.status_code==200
        a,b=first.json(),second.json()
        assert a['app_user_id']!=b['app_user_id'] and a['displayName']=='Nick'
        assert a['idToken'] and a['refreshToken'] is None
    with setup.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM accounts.account_records').fetchone()[0]==2
        rows=con.execute('SELECT * FROM accounts.account_consents WHERE app_user_id=?',(a['app_user_id'],)).fetchall()
        assert {r['policy_kind'] for r in rows}=={'terms','privacy'}
        assert all(r['version']==VERSION and r['accepted_at'] for r in rows)
        assert con.execute('SELECT account_type FROM users WHERE id=?',(a['user_id'],)).fetchone()[0]=='user'
        assert con.execute('SELECT account_type FROM users WHERE id=?',(b['user_id'],)).fetchone()[0]=='shop'
        assert con.execute('SELECT account_type FROM accounts.account_records WHERE id=?',(b['user_id'],)).fetchone()[0]=='shop'


def test_registration_consent_failure_rolls_back_account_and_projection(setup):
    from ygc.registration import register, VERSION
    with setup.connect() as con:
        con.execute("CREATE TRIGGER accounts.reject_test_consent BEFORE INSERT ON account_consents BEGIN SELECT RAISE(ABORT,'test consent failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        register(setup,{'display_name':'Nick','terms_accepted':True,'privacy_accepted':True,'terms_version':VERSION,'privacy_version':VERSION})
    with setup.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
        assert con.execute('SELECT COUNT(*) FROM accounts.account_records').fetchone()[0]==0


def test_registration_consents_belong_to_account_backup_and_old_archives_migrate(setup):
    from ygc.registration import register, VERSION
    user_id=register(setup,{'display_name':'Nick','terms_accepted':True,'privacy_accepted':True,'terms_version':VERSION,'privacy_version':VERSION})
    saved=crawl_backups.create(web.api_export_db,'accounts','manual')
    with zipfile.ZipFile(crawl_backups.selected(saved)) as archive:
        snapshot=config.DATA_DIR/'consent_snapshot.sqlite'
        snapshot.write_bytes(archive.read('database.sqlite'))
    with sqlite3.connect(snapshot) as con:
        assert con.execute('SELECT COUNT(*) FROM account_consents').fetchone()[0]==2
    # Simulate an account backup from before consent support. No historic consent is invented.
    with sqlite3.connect(config.ACCOUNTS_DB_PATH) as con:
        con.execute('DROP TABLE account_consents')
    with setup.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM accounts.account_consents').fetchone()[0]==0
    assert setup.get_user(user_id)[0]['display_name']=='Nick'
