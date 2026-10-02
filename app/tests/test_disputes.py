import sqlite3
import pytest
from ygc import disputes as d, acquire_review as ar
from test_acquire_review import setup, submitted, claim, complete
from authentication_fixtures import image_bytes


def acquired(env):
    repo,a,b,c,i=env
    r=submitted(env);complete(repo,claim(repo))
    with repo.connect() as con:return ar.find(con,r['revision'])['claim_id']


def opening(env,cid,user=None):
    repo,a,b,c,i=env
    with ar.transaction(repo) as con:
        return d.open_case(con,cid,user or b,'I purchased this guitar','Purchase claim',b'%PDF-1.4 evidence','application/pdf','document.pdf')


def decide(env,did,action='owner',winner=None):
    repo,*_=env
    with ar.transaction(repo) as con:
        case=d.get_case(con,did,admin=True)
        if action!='reopen':
            rnd=d.current_round(con,did)
            for party in con.execute('SELECT * FROM ownership_dispute_round_parties WHERE round_id=? AND submitted_at IS NULL',(rnd['id'],)).fetchall():
                d.add_evidence(con,case,party['claim_id'],party['user_id'],'Explanation','Summary',b'',None,None,expected_round=rnd['number'])
            case=d.get_case(con,did,admin=True)
        d.decide(repo,con,did,case['version'],action,'Reviewed purchase records',winner)


def test_decline_requires_reason_and_keeps_owner(setup):
    repo,a,b,c,i=setup;cid=acquired(setup)
    with pytest.raises(ValueError,match='reason'):repo.set_claim_response(cid,a,'negative')
    assert repo.get_individual(i)[0]['current_owner_user_id']==a
    repo.set_claim_response(cid,a,'negative','The guitar is on loan')
    with repo.connect() as con:
        assert con.execute('SELECT reason FROM ownership_declines WHERE claim_id=?',(cid,)).fetchone()[0]=='The guitar is on loan'
        assert con.execute("SELECT COUNT(*) FROM notifications WHERE notification_type='ownership_decline' AND recipient_user_id=?",(b,)).fetchone()[0]==1


def test_owner_decision_locks_claim_without_changing_author(setup):
    repo,a,b,c,i=setup;cid=acquired(setup)
    repo.set_claim_response(cid,a,'negative','On loan');did=opening(setup,cid)
    assert cid not in repo.owner_verifiable_claim_ids(i,a)
    with pytest.raises((ValueError,sqlite3.IntegrityError)):repo.set_claim_response(cid,a,'positive')
    with pytest.raises(sqlite3.IntegrityError):repo.update_claim(cid,b,occurred_at='2026-02-01',body='changed')
    with pytest.raises(sqlite3.IntegrityError):repo.deactivate_claim(cid,b)
    with pytest.raises(sqlite3.IntegrityError):repo.create_transfer(a,i,c)
    with pytest.raises(sqlite3.IntegrityError):repo.create_ownership_claim(a,i,ownership_kind='release')
    with pytest.raises(sqlite3.IntegrityError):repo.admin_moderate_claim(cid,'positive')
    decide(setup,did)
    assert repo.get_individual(i)[0]['current_owner_user_id']==a
    with repo.connect() as con:
        r=con.execute('SELECT * FROM claims WHERE id=?',(cid,)).fetchone()
        assert r['author_user_id']==b and r['verification_status']=='negative'
    with pytest.raises(ValueError):repo.set_claim_response(cid,a,'positive')
    with pytest.raises(sqlite3.IntegrityError):repo.admin_moderate_claim(cid,'delete')
    # Future ownership Claims are permitted after resolution.
    tid=repo.create_transfer(a,i,c);repo.resolve_transfer(tid,c,'accept')
    assert repo.get_individual(i)[0]['current_owner_user_id']==c
    with pytest.raises(ValueError):repo.set_claim_response(cid,c,'positive')
    with pytest.raises(ValueError,match='changed'):decide(setup,did,'reopen')


def test_applicant_decision_moves_authority_and_can_be_reconsidered(setup):
    repo,a,b,c,i=setup;cid=acquired(setup)
    repo.set_claim_response(cid,a,'negative','Disagree');did=opening(setup,cid)
    decide(setup,did,'applicant',cid)
    assert repo.get_individual(i)[0]['current_owner_user_id']==b
    with pytest.raises(ValueError):repo.set_claim_response(cid,b,'negative')
    with pytest.raises(ValueError):repo.set_claim_response(cid,a,'negative','again')
    decide(setup,did,'reopen')
    with repo.connect() as con:
        assert d.detail(con,did,a)['status']=='open'
        assert d.detail(con,did,b)['status']=='open'
    decide(setup,did,'owner')
    assert repo.get_individual(i)[0]['current_owner_user_id']==a


def test_evidence_is_private_and_append_only(setup):
    repo,a,b,c,i=setup;cid=acquired(setup)
    repo.set_claim_response(cid,a,'negative','Disagree');did=opening(setup,cid)
    with ar.transaction(repo) as con:
        assert not d.detail(con,did,a)['evidence']
        assert d.detail(con,did,b)['evidence'][0]['explanation']=='I purchased this guitar'
        with pytest.raises(PermissionError):d.detail(con,did,c)
        evidence=d.detail(con,did,admin=True)['evidence'][0]
        con.execute('UPDATE ownership_dispute_evidence SET published_summary=?,published_at=? WHERE id=?',('Claimed purchase',d.utcnow(),evidence['id']))
        other=d.detail(con,did,a)['evidence'][0]
        assert other['published_summary']=='Claimed purchase'
        assert 'explanation' not in other and 'has_attachment' not in other
        d.add_evidence(con,d.get_case(con,did,a),cid,a,'Loan agreement','Loan',b'',None,None)
        assert len(d.detail(con,did,admin=True)['evidence'])==2


def test_unanswered_wait_and_formerly_owned_exclusion(setup):
    repo,a,b,c,i=setup;cid=acquired(setup)
    with pytest.raises(ValueError,match='days'):opening(setup,cid)
    with repo.connect() as con:con.execute("UPDATE claims SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?",(cid,))
    did=opening(setup,cid)
    assert did


def test_backdated_acquire_cannot_open_dispute(setup):
    repo,a,b,c,i=setup;cid=acquired(setup)
    with repo.connect() as con:
        con.execute("UPDATE claims SET occurred_at='2025-01-01' WHERE id=?",(cid,))
        assert not d.eligible(con,d.candidate(con,cid))
    with pytest.raises(ValueError,match='Current Owner'):opening(setup,cid)


def test_multiple_applicants_share_one_case_with_separate_evidence(setup):
    repo,a,b,c,i=setup;first=acquired(setup)
    submitted(setup,user=c);complete(repo,claim(repo))
    with repo.connect() as con:second=con.execute('SELECT claim_id FROM acquire_applications WHERE applicant_id=?',(c,)).fetchone()[0]
    repo.set_claim_response(first,a,'negative','Disagree B');repo.set_claim_response(second,a,'negative','Disagree C')
    did=opening(setup,first);assert opening(setup,second,c)==did
    with repo.connect() as con:
        assert len(d.detail(con,did,b)['claims'])==1
        assert len(d.detail(con,did,c)['claims'])==1
        assert len(d.detail(con,did,a)['claims'])==2
    decide(setup,did,'applicant',first)
    assert repo.get_individual(i)[0]['current_owner_user_id']==b


def test_stale_admin_decision_is_rejected(setup):
    repo,a,b,c,i=setup;cid=acquired(setup);repo.set_claim_response(cid,a,'negative','Disagree');did=opening(setup,cid)
    with ar.transaction(repo) as con:
        with pytest.raises(ValueError,match='changed'):d.decide(repo,con,did,1,'owner','Reviewed')
    assert repo.get_individual(i)[0]['current_owner_user_id']==a


def test_image_evidence_is_sanitized():
    data,mime,name=d.validate_submission('explanation','summary',image_bytes(),'unsafe.html')
    assert data.startswith(b'\xff\xd8') and mime=='image/jpeg' and name=='photo.jpg'


def test_http_privacy_summary_publication_and_decision(setup):
    from fastapi.testclient import TestClient
    from ygc.web import app,CONSOLE_ADMIN_TOKEN
    repo,a,b,c,i=setup;cid=acquired(setup)
    client=TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',12345))
    response=client.post(f'/api/claims/{cid}/response',json={'responder_user_id':a,'stance':'negative'})
    assert response.status_code==400
    assert client.post(f'/api/claims/{cid}/response',json={'responder_user_id':a,'stance':'negative','reason':'On loan'}).status_code==200
    response=client.post(f'/api/ownership-disputes/evidence/submit?viewer_id={b}',data={'claim_id':cid,'explanation':'Purchased it','summary':'Purchase'},files={'attachment':('proof.png',image_bytes(),'image/png')})
    assert response.status_code==200,response.text
    case=response.json();did=case['id'];eid=case['evidence'][0]['id']
    assert client.get(f'/api/ownership-disputes/{did}?viewer_id={c}').status_code==403
    assert client.get(f'/api/ownership-dispute-evidence/{eid}?viewer_id={a}').status_code==403
    raw=client.get(f'/api/ownership-dispute-evidence/{eid}?viewer_id={b}')
    assert raw.status_code==200 and raw.headers['cache-control']=='private, no-store'
    assert 'attachment' in raw.headers['content-disposition']
    assert client.get('/api/admin/ownership-disputes').status_code==403
    headers={'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}
    response=client.post(f'/api/admin/ownership-dispute-evidence/{eid}/publish',headers=headers,json={'version':case['version'],'summary':'The applicant claims a purchase.'})
    assert response.status_code==200,response.text
    case=response.json()
    seen=client.get(f'/api/ownership-disputes/{did}?viewer_id={a}').json()['evidence'][0]
    assert seen['published_summary'] and 'explanation' not in seen
    assert client.post(f'/api/admin/ownership-dispute-evidence/{eid}/publish',headers=headers,json={'version':case['version'],'summary':'Overwrite'}).status_code==409
    response=client.post(f'/api/ownership-disputes/evidence/submit?viewer_id={a}',data={'claim_id':cid,'case_id':did,'round_number':1,'explanation':'Loan agreement','summary':'Loan'})
    assert response.status_code==200,response.text
    case=response.json()
    response=client.post(f'/api/admin/ownership-disputes/{did}/decision',headers=headers,json={'version':case['version'],'action':'owner','reason':'Loan evidence accepted'})
    assert response.status_code==200,response.text
    assert client.post(f'/api/claims/{cid}/response',json={'responder_user_id':a,'stance':'positive'}).status_code==400


def test_pending_transfer_and_new_acquire_cannot_change_disputed_owner(setup):
    repo,a,b,c,i=setup;cid=acquired(setup)
    transfer=repo.create_transfer(a,i,c)
    r=submitted(setup,user=c);job=claim(repo)
    repo.set_claim_response(cid,a,'negative','Loan');did=opening(setup,cid)
    with pytest.raises(sqlite3.IntegrityError):repo.resolve_transfer(transfer,c,'accept')
    with pytest.raises((sqlite3.IntegrityError,ValueError)):complete(repo,job)
    assert repo.get_individual(i)[0]['current_owner_user_id']==a
    with repo.connect() as con:
        assert not con.execute('SELECT 1 FROM claim_transfer_acceptance WHERE claim_id=?',(transfer,)).fetchone()
        assert d.get_case(con,did,a)['status']=='open'


def test_locks_survive_restart_and_admin_queue_skips_paused_guitar(setup):
    repo,a,b,c,i=setup;cid=acquired(setup)
    submitted(setup,user=c)
    repo.set_claim_response(cid,a,'negative','Loan');did=opening(setup,cid)
    repo.init_db()
    assert not ar.call_tool(repo,'ygc_pending_acquire',{})['jobs']
    assert not repo.unanswered_ownership_requests(a)
    with pytest.raises(sqlite3.IntegrityError):repo.create_transfer(a,i,c)
    decide(setup,did)
    repo.init_db()
    assert ar.call_tool(repo,'ygc_pending_acquire',{})['jobs']


def test_two_concurrent_appeals_share_a_case(setup):
    from concurrent.futures import ThreadPoolExecutor
    repo,a,b,c,i=setup;first=acquired(setup)
    submitted(setup,user=c);complete(repo,claim(repo))
    with repo.connect() as con:second=con.execute('SELECT claim_id FROM acquire_applications WHERE applicant_id=?',(c,)).fetchone()[0]
    repo.set_claim_response(first,a,'negative','No');repo.set_claim_response(second,a,'negative','No')
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(opening,setup,first,b),pool.submit(opening,setup,second,c)]
        ids=[f.result() for f in futures]
    assert ids[0]==ids[1]


def test_disputed_product_reports_private_ui_lock_and_blocks_new_previews(setup):
    from fastapi.testclient import TestClient
    from ygc.web import app
    repo,a,b,c,i=setup;cid=acquired(setup)
    repo.set_claim_response(cid,a,'negative','Loan');did=opening(setup,cid)
    client=TestClient(app)
    for actor in (a,b):
        row=client.get(f'/api/individuals/{i}?viewer_user_id={actor}').json()['individual']
        assert row['ownership_dispute_id']==did
    for suffix in ('',f'?viewer_user_id={c}'):
        assert 'ownership_dispute_id' not in client.get(f'/api/individuals/{i}'+suffix).json()['individual']
    with pytest.raises(ValueError,match='paused'):ar.start(repo,c,i,preview=True)
    decide(setup,did)
    assert 'ownership_dispute_id' not in client.get(f'/api/individuals/{i}?viewer_user_id={a}').json()['individual']
    assert ar.start(repo,c,i,preview=True)['unsaved']


def test_rounds_require_both_parties_and_only_admin_can_start_next(setup):
    repo,a,b,c,i=setup;cid=acquired(setup)
    repo.set_claim_response(cid,a,'negative','Loan');did=opening(setup,cid)
    with ar.transaction(repo) as con:
        case=d.get_case(con,did,b)
        rnd=d.detail(con,did,b)['round']
        assert rnd['number']==1 and rnd['phase']=='collecting'
        assert next(p for p in rnd['parties'] if p['user_id']==b)['submitted_at']
        assert not next(p for p in rnd['parties'] if p['user_id']==a)['submitted_at']
        with pytest.raises(ValueError,match='already submitted'):
            d.add_evidence(con,case,cid,b,'Again','Again',b'',None,None,expected_round=1)
        with pytest.raises(ValueError,match='Both parties'):
            d.decide(repo,con,did,case['version'],'request_evidence','Review',cid)
        d.add_evidence(con,case,cid,a,'Loan papers','Loan',b'',None,None,expected_round=1)
        assert d.current_round(con,did)['phase']=='reviewing'
        with pytest.raises(ValueError,match='Under review'):
            d.add_evidence(con,case,cid,a,'More','More',b'',None,None,expected_round=1)
        case=d.get_case(con,did,admin=True)
        d.decide(repo,con,did,case['version'],'request_evidence','Please clarify the acquisition date')
        assert d.current_round(con,did)['number']==2
        assert d.current_round(con,did)['phase']=='collecting'
        case=d.get_case(con,did,b)
        with pytest.raises(ValueError,match='round has changed'):
            d.add_evidence(con,case,cid,b,'Old tab','Old tab',b'',None,None,expected_round=1)
        for actor in (a,b):
            d.add_evidence(con,case,cid,actor,'Clarification','Clarification',b'',None,None,expected_round=2)
        assert d.current_round(con,did)['phase']=='reviewing'
        detail=d.detail(con,did,admin=True)
        assert {e['round_number'] for e in detail['evidence']}=={1,2}
        assert [r['number'] for r in detail['rounds']]==[1,2]
        assert detail['current_owner_name']
        assert detail['claims'][0]['requested_at']
        assert next(e for e in detail['events'] if e['kind']=='opened')['round_number']==1
        assert next(e for e in detail['events'] if e['kind']=='request_evidence')['round_number']==2
    decide(setup,did,'owner')


def test_existing_evidence_round_migration_preserves_records(setup):
    repo,a,b,c,i=setup;cid=acquired(setup)
    repo.set_claim_response(cid,a,'negative','Loan');did=opening(setup,cid)
    with repo.connect() as con:
        original=[tuple(r) for r in con.execute('SELECT * FROM ownership_dispute_evidence')]
        con.execute('DELETE FROM ownership_dispute_round_evidence')
        con.execute('DELETE FROM ownership_dispute_round_parties')
        con.execute('DELETE FROM ownership_dispute_rounds')
    repo.init_db();repo.init_db()
    with repo.connect() as con:
        assert [tuple(r) for r in con.execute('SELECT * FROM ownership_dispute_evidence')]==original
        rnd=d.detail(con,did,b)['round']
        assert rnd['number']==1 and rnd['phase']=='collecting'
        assert next(p for p in rnd['parties'] if p['user_id']==b)['submitted_at']
        assert con.execute('SELECT COUNT(*) FROM ownership_dispute_rounds').fetchone()[0]==1


@pytest.mark.parametrize('action', ['owner', 'applicant'])
@pytest.mark.parametrize('empty_round', [False, True])
def test_admin_can_decide_without_waiting_for_evidence(setup, action, empty_round):
    repo,a,b,c,i=setup;cid=acquired(setup)
    repo.set_claim_response(cid,a,'negative','Loan');did=opening(setup,cid)
    if empty_round:
        decide(setup,did,'owner')
        decide(setup,did,'reopen')
    with ar.transaction(repo) as con:
        case=d.get_case(con,did,admin=True)
        rnd=d.detail(con,did,admin=True)['round']
        assert rnd['phase']=='collecting'
        assert sum(bool(p['submitted_at']) for p in rnd['parties'])==(0 if empty_round else 1)
        d.decide(repo,con,did,case['version'],action,'Administrative decision despite outstanding evidence',cid)
        assert d.get_case(con,did,admin=True)['status']=='resolved'
        assert d.current_round(con,did)['phase']=='collecting'
    assert repo.get_individual(i)[0]['current_owner_user_id']==(a if action=='owner' else b)
    assert cid not in repo.owner_verifiable_claim_ids(i,a if action=='owner' else b)
