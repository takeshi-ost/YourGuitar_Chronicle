import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from ygc import config
from ygc.db.repository import Repository
from ygc.observation_evaluator import evaluate_observation
from ygc.web import app


def setup(tmp_path):
    r=Repository(tmp_path/'transfer.db');r.init_db()
    a,b,c=[r.create_user(n) for n in ('From','To','Other')]
    g,*_=r.create_initial_listing_claim(a,manufacturer='Fender',model='Telecaster',serial_number='TRANSFER01',media_storage_path='media/test.jpg',occurred_at='2026-01-01')
    return r,a,b,c,g


def owner(r,g):
    return int(r.get_individual(g)[0]['current_owner_user_id'])


def test_accept_evidence_observation_history_and_existing_verification(tmp_path):
    r,a,b,c,g=setup(tmp_path)
    cid=r.create_transfer(a,g,b)
    assert owner(r,g)==a
    with pytest.raises(ValueError,match='Use Cancel'):r.deactivate_claim(cid,a)
    assert r.get_user(b)[1]==[]
    assert r.list_notifications(b)[0]['notification_type']=='transfer_request'
    assert cid not in r.owner_verifiable_claim_ids(g,a)
    assert cid not in r.owner_verifiable_claim_ids(g,b)
    with pytest.raises(ValueError,match='participant'):r.resolve_transfer(cid,c,'accept')
    assert r.resolve_transfer(cid,b,'accept')['state']=='accepted'
    assert owner(r,g)==b
    t=r.transfer_details(cid)
    assert t['accepted_by_user_id']==b and t['current_owner_user_id']==a
    claim=next(x for x in r.list_claims(g) if x['id']==cid)
    assert t['accepted_at']==claim['occurred_at']
    assert claim['author_user_id']==a
    assert claim['verification_status']=='positive'
    assert r.get_user(a)[1][0]['ownership_status']=='former_owner'
    assert r.get_user(b)[1][0]['ownership_status']=='current_owner'
    assert r.get_user_summary(a)['former_count']==1
    assert r.get_user_summary(b)['owned_count']==1
    with r.connect() as con:
        evaluated=evaluate_observation(con,g)
        assert any(d['claim_id']==cid and any(e['evidence_type']=='transfer_acceptance' for e in d['evidence']) for d in evaluated.decisions)
        before=con.execute('SELECT COUNT(*) FROM notifications').fetchone()[0]
    r.resolve_transfer(cid,b,'accept')  # retry does not create evidence or notify twice
    with r.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM notifications').fetchone()[0]==before
        assert con.execute('SELECT COUNT(*) FROM claim_transfer_acceptance').fetchone()[0]==1
    diagnostic=r.observation_diagnostic(g)
    assert diagnostic['differences']=={}
    matrix_claim=next(x for x in diagnostic['matrix']['rows'] if x['claim_id']==cid)
    assert matrix_claim['cells']['current_owner_user_id']['value']==str(b)
    assert cid not in r.owner_verifiable_claim_ids(g,b)
    for stance in ('positive', 'negative', 'unverified'):
        with pytest.raises(ValueError, match='recipient cannot change'):
            r.set_claim_response(cid,b,stance)
        assert owner(r,g)==b
        assert r.transfer_details(cid)==t
        assert r.get_user_summary(a)['former_count']==1
        assert r.get_user_summary(b)['owned_count']==1
    r.admin_moderate_claim(cid,'negative')
    assert owner(r,g)==a
    assert r.transfer_details(cid)==t  # Negative is not Decline and does not withdraw agreement.
    r.resolve_transfer(cid,b,'accept')
    assert owner(r,g)==a  # Retrying Accept cannot overwrite a later Verification.
    with pytest.raises(ValueError,match='cannot be edited'):
        r.update_claim(cid,a,occurred_at='2020-01-01')
    with pytest.raises(ValueError):r.set_claim_response(cid,a,'positive')
    with pytest.raises(ValueError):r.set_claim_response(cid,b,'positive')
    r.admin_moderate_claim(cid,'positive')
    assert owner(r,g)==b
    next_id=r.create_transfer(b,g,c)
    r.resolve_transfer(next_id,c,'accept')
    assert owner(r,g)==c
    assert r.get_user_summary(b)['former_count']==1
    assert next_id not in r.owner_verifiable_claim_ids(g,c)
    # A later, unrelated owner can still verify another user's historical Transfer.
    assert cid in r.owner_verifiable_claim_ids(g,c)


def test_decline_cancel_competing_and_no_admin_bypass_of_acceptance(tmp_path):
    r,a,b,c,g=setup(tmp_path)
    declined=r.create_transfer(a,g,b)
    r.resolve_transfer(declined,b,'decline')
    assert owner(r,g)==a
    assert r.transfer_details(declined)['accepted_at'] is None
    assert next(x for x in r.list_claims(g) if x['id']==declined)['verification_status']=='unverified'
    r.admin_moderate_claim(declined,'positive')
    assert owner(r,g)==a
    cancelled=r.create_transfer(a,g,b)
    r.resolve_transfer(cancelled,a,'cancel')
    assert owner(r,g)==a
    with pytest.raises(ValueError):r.resolve_transfer(cancelled,b,'accept')
    x=r.create_transfer(a,g,b);y=r.create_transfer(a,g,c)
    def accept(pair):
        try:return r.resolve_transfer(*pair,'accept')['state']
        except ValueError:return 'rejected'
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(accept,[(x,b),(y,c)]))
    assert sorted(results)==['accepted','rejected']
    assert owner(r,g) in (b,c)
    with r.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM claim_transfer_acceptance').fetchone()[0]==1


def test_transfer_api_restrictions_search_and_claim_metadata(tmp_path,monkeypatch):
    r,a,b,c,g=setup(tmp_path)
    monkeypatch.setattr(config,'DB_PATH',r.db_path)
    with TestClient(app) as client:
        url=f'/api/individuals/{g}/transfers'
        assert client.post(url,json={'to_user_id':b}).status_code==401
        assert client.post(url+f'?viewer_id={c}',json={'to_user_id':b}).status_code==403
        assert client.post(url+f'?viewer_id={a}',json={'to_user_id':a}).status_code==409
        assert client.get(f'/api/transfer-users?viewer_id={a}&q=To').json()==[{'id':b,'display_name':'To','account_type':'user'}]
        assert client.get(f'/api/transfer-users?viewer_id={a}&q={b}').json()[0]['id']==b
        assert client.get(f'/api/transfer-users?viewer_id={a}&q=From').json()==[]
        proposal=client.post(url+f'?viewer_id={a}',json={'to_user_id':b}).json()
        cid=proposal['claim_id']
        assert client.get(f'/api/transfers/{cid}?viewer_id={c}').status_code==403
        claims=client.get(f'/api/individuals/{g}/claims?viewer_user_id={b}').json()
        assert next(x for x in claims if x['id']==cid)['transfer']['state']=='pending'
        assert client.post(f'/api/transfers/{cid}/resolve?viewer_id={a}',json={'action':'accept'}).status_code==403
        with r.connect() as con:con.execute("UPDATE users SET ban_status='ban' WHERE id=?",(b,))
        assert client.post(f'/api/transfers/{cid}/resolve?viewer_id={b}',json={'action':'accept'}).status_code==404
        assert owner(r,g)==a
        with r.connect() as con:con.execute("UPDATE users SET ban_status='normal' WHERE id=?",(b,))
        assert client.post(f'/api/transfers/{cid}/resolve?viewer_id={b}',json={'action':'accept'}).status_code==200
        assert client.get(f'/api/users/{b}/profile?viewer_id={b}').json()['guitars'][0]['ownership_status']=='current_owner'
        assert client.get(f'/api/users/{a}/profile?viewer_id={a}').json()['guitars'][0]['ownership_status']=='former_owner'
        claims=client.get(f'/api/individuals/{g}/claims?viewer_user_id={b}').json()
        assert next(x for x in claims if x['id']==cid)['can_verify'] is False
        before=r.transfer_details(cid)
        for actor in (a,b,c):
            for stance in ('negative','unverified'):
                response=client.post(f'/api/claims/{cid}/response',json={
                    'responder_user_id':actor,'stance':stance})
                assert response.status_code==400
                assert owner(r,g)==b
                assert r.transfer_details(cid)==before


@pytest.mark.parametrize('stance', ['negative', 'unverified'])
def test_admin_can_override_transfer_without_erasing_acceptance(tmp_path, stance):
    r,a,b,c,g=setup(tmp_path)
    cid=r.create_transfer(a,g,b)
    r.resolve_transfer(cid,b,'accept')
    evidence=r.transfer_details(cid)
    r.admin_moderate_claim(cid,stance)
    assert owner(r,g)==a
    assert r.transfer_details(cid)==evidence
    r.resolve_transfer(cid,b,'accept')
    assert owner(r,g)==a
    assert next(x for x in r.list_claims(g) if x['id']==cid)['verification_status']==stance
    r.admin_moderate_claim(cid,'positive')
    assert owner(r,g)==b
    assert r.transfer_details(cid)==evidence
    assert cid not in r.owner_verifiable_claim_ids(g,b)


def test_existing_database_and_legacy_transfer_preserved(tmp_path):
    path=tmp_path/'old.db'
    schema=(Path(__file__).parents[1]/'src/ygc/db/schema.sql').read_text().split('CREATE TABLE IF NOT EXISTS claim_transfers')[0]
    with sqlite3.connect(path) as con:con.executescript(schema)
    r=Repository(path);r.init_db()
    a,b=[r.create_user(n) for n in ('A','B')]
    g,*_=r.create_initial_listing_claim(a,manufacturer='Fender',model='Telecaster',serial_number='LEGTRANS01',media_storage_path='media/test.jpg',occurred_at='2026-01-01')
    with r.connect() as con:
        con.execute("""INSERT INTO claims (individual_id,author_user_id,claim_type,ownership_kind,value_text,occurred_at,status,verification_status,created_at,updated_at)
             VALUES (?,?,'ownership','transfer','unknown','2026-02-01','active','positive','2026-02-01','2026-02-01')""",(g,a))
        assert evaluate_observation(con,g).values['current_owner_user_id'] is None
    r.init_db()
    with pytest.raises(ValueError,match='workflow'):r.create_ownership_claim(a,g,ownership_kind='transfer')


@pytest.mark.parametrize('change', ['negative', 'unverified', 'admin_negative', 'delete', 'deactivate'])
def test_later_transfer_is_independent_of_earlier_transfer(tmp_path, change):
    r,a,b,c,g=setup(tmp_path)
    first=r.create_transfer(a,g,b)
    r.resolve_transfer(first,b,'accept')
    second=r.create_transfer(b,g,c)
    r.resolve_transfer(second,c,'accept')
    evidence=r.transfer_details(second)
    if change in ('negative', 'unverified'):
        r.set_claim_response(first,c,change)
    elif change == 'deactivate':
        r.deactivate_claim(first,a)
    else:
        r.admin_moderate_claim(first,'negative' if change == 'admin_negative' else 'delete')
    assert owner(r,g)==c
    assert r.transfer_details(second)==evidence
    assert r.get_user_summary(c)['owned_count']==1
    assert r.get_user_summary(b)['former_count']==1
    assert second not in r.owner_verifiable_claim_ids(g,c)
    assert r.owner_verifiable_claim_ids(g,b)==set()
    assert r.observation_diagnostic(g)['differences']=={}
    with r.connect() as con:
        evaluated=evaluate_observation(con,g)
        assert evaluated.sources['current_owner_user_id']==second
    with pytest.raises(ValueError, match='recipient cannot change'):
        r.set_claim_response(second,c,'negative')


def test_transfer_checks_owner_at_acceptance_and_preserves_day_id_order(tmp_path, monkeypatch):
    r,a,b,c,g=setup(tmp_path)
    monkeypatch.setattr('ygc.db.repository.utcnow', lambda: '2026-10-01T10:00:00Z')
    older=r.create_transfer(a,g,c)
    first=r.create_transfer(a,g,b)
    r.resolve_transfer(first,b,'accept')
    with pytest.raises(ValueError, match='Current Owner changed'):
        r.resolve_transfer(older,c,'accept')
    second=r.create_transfer(b,g,a)
    r.resolve_transfer(second,a,'accept')
    monkeypatch.setattr('ygc.db.repository.utcnow', lambda: '2026-10-01T11:00:00Z')
    with pytest.raises(ValueError, match='chronology'):
        r.resolve_transfer(older,c,'accept')
    assert owner(r,g)==a
    assert r.transfer_details(older)['state']=='pending'
    assert r.transfer_details(older)['accepted_at'] is None
    assert r.get_user(c)[1]==[]
    # A later calendar day takes precedence over the lower Claim ID.
    monkeypatch.setattr('ygc.db.repository.utcnow', lambda: '2026-10-02T10:00:00Z')
    r.resolve_transfer(older,c,'accept')
    assert owner(r,g)==c
    assert r.observation_diagnostic(g)['differences']=={}


@pytest.mark.parametrize('field', ['accepted_by_user_id', 'current_owner_user_id', 'accepted_at'])
def test_independent_transfer_still_requires_consistent_acceptance_evidence(tmp_path, field):
    r,a,b,c,g=setup(tmp_path)
    cid=r.create_transfer(a,g,b)
    r.resolve_transfer(cid,b,'accept')
    with r.connect() as con:
        value='2020-01-01' if field=='accepted_at' else c
        con.execute(f'UPDATE claim_transfer_acceptance SET {field}=? WHERE claim_id=?', (value,cid))
        evaluated=evaluate_observation(con,g)
        assert str(evaluated.values['current_owner_user_id'])==str(a)
        assert any(d['claim_id']==cid and d.get('reason')=='missing_or_invalid_transfer_acceptance'
                   for d in evaluated.decisions)
