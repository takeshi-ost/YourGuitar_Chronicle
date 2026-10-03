from fastapi.testclient import TestClient
from ygc import config, web, operations, acquire_review, important_information
from ygc.db.repository import Repository


def test_private_summary_deadline_result_seen_and_transfer_lifecycle(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    r=Repository(tmp_path/'db');r.init_db()
    owner=r.create_user('Owner');applicant=r.create_user('Applicant');other=r.create_user('Other')
    individual,*_=r.create_initial_listing_claim(owner,manufacturer='Fender',model='Tele',serial_number='ABC123',media_storage_path='reference.png',occurred_at='2026-01-01')
    draft=acquire_review.start(r,applicant,individual)
    summary=important_information.for_user(r,applicant)
    assert summary['applications'][0]['expires_at']==draft['expires_at']
    assert summary['applications'][0]['status']=='draft'
    assert important_information.for_user(r,other)['applications']==[]
    with r.connect() as con:
        con.execute("UPDATE acquire_applications SET status='rejected' WHERE revision=?",(draft['revision'],))
        con.execute("INSERT INTO acquire_application_events(revision,at,kind,note) VALUES (?,'2026-10-03','rejected','test')",(draft['revision'],))
    assert important_information.for_user(r,applicant)['applications']==[]
    with acquire_review.transaction(r) as con:row=acquire_review.detail(con,draft['revision'],applicant)
    acquire_review.mark_seen(r,applicant,draft['revision'],row['review_event_id'])
    assert important_information.for_user(r,applicant)['applications']==[]
    transfer=r.create_transfer(owner,individual,other)
    assert important_information.for_user(r,owner)['outgoing_transfers'][0]['claim_id']==transfer
    assert r.unanswered_ownership_requests(other)[0]['claim_id']==transfer
    r.resolve_transfer(transfer,other,'decline')
    assert important_information.for_user(r,owner)['outgoing_transfers']==[]
    assert important_information.for_user(r,owner)['transfer_results']==[]
    result=dict(next(row for row in r.list_notifications(owner) if row['notification_type']=='transfer_result'))
    assert important_information.for_user(r,applicant)['transfer_results']==[]
    r.mark_notification_read(result['id'],owner)
    assert important_information.for_user(r,owner)['transfer_results']==[]


def test_public_notice_survives_offline_and_private_summary_requires_actor(tmp_path,monkeypatch):
    monkeypatch.setenv('YGC_IDENTITY_BACKEND','local_dummy')
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'chronicle.db')
    monkeypatch.setattr(config,'ACCOUNTS_DB_PATH',tmp_path/'accounts.sqlite')
    r=web.repo();r.init_db();a=r.create_user('A');b=r.create_user('B')
    with TestClient(web.app,base_url='http://127.0.0.1',client=('127.0.0.1',45000)) as c:
        assert c.get('/api/important-information').status_code==401
        token=c.post('/api/local-auth/login',json={'user_id':a}).json()['token']
        headers={'Authorization':'Bearer '+token}
        assert c.get('/api/important-information',headers=headers).status_code==200
        assert c.get('/api/important-information?viewer_id='+str(b),headers=headers).status_code==403
        assert c.get('/assets/important-information.js').status_code==200
        operations.update('offline','Maintenance test','',0)
        notice=c.get('/api/service-notice')
        assert notice.status_code==200 and notice.json()['message']=='Maintenance test'
        assert notice.headers['cache-control']=='no-store'
        assert c.get('/api/important-information',headers=headers).status_code==503
