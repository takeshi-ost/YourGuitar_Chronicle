from contextlib import contextmanager
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_cloud_claims import services
from ygc.cloud_owner import CloudOwner
from ygc.cloud_owner_routes import owner_router
from ygc.identity_platform import VerifiedIdentity
from ygc.db.postgres_operations import ServiceRestricted


def prepare(services,monkeypatch):
    repo,_,owner,a,b,c,guitar=services
    @contextmanager
    def access(kind,actor):
        assert kind=='user_read'
        yield None,None,{'id':actor}
    owner.operations=Mock();owner.operations.access=access
    class Adapter:
        def __init__(self,con):self.con=con
        def execute(self,sql,params=()):
            if sql.startswith('SET LOCAL'):return None
            return self.con.execute(sql.replace('%s','?'),params)
    @contextmanager
    def connect(*args):
        with repo.connect() as con:yield Adapter(con)
    monkeypatch.setattr('ygc.cloud_owner.connect',connect)
    def acquire(user,date='2025-01-01'):
        _,claim=repo.create_ownership_claim(user,guitar,ownership_kind='acquire',occurred_at=date)
        with repo.connect() as con:
            con.execute("""INSERT INTO acquire_applications(revision,applicant_id,individual_id,original_individual_id,
                serial,challenge,expires_at,created_at,status,prompt_version,claim_id)
                VALUES (?,?,?,?,'FIXTURE','FIXTURE',0,'2025-01-01','accepted','synthetic',?)""",
                ('fixture-'+str(claim),user,guitar,guitar,claim))
        return claim
    return repo,owner,a,b,c,guitar,acquire


def test_inbox_owner_transition_and_self_claim_isolation(services,monkeypatch):
    repo,owner,a,b,c,guitar,acquire=prepare(services,monkeypatch)
    claim=acquire(b)
    assert [x['id'] for x in owner.inbox(a)['items']]==[str(claim)]
    assert owner.inbox(b)['items']==owner.inbox(c)['items']==[]
    row=owner.pending(a,guitar)['items'][0]
    owner.respond(a,guitar,claim,{'stance':'positive','revision':row['revision']})
    with repo.connect() as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=?',(guitar,)).fetchone()[0]==b
    assert owner.inbox(a)['items']==owner.inbox(b)['items']==[]
    assert not any(x['id']==str(claim) for x in owner.pending(b,guitar)['items'])
    # New owner receives a later re-acquisition; former owner cannot answer it.
    again=acquire(a,'2025-02-01')
    assert [x['id'] for x in owner.inbox(b)['items']]==[str(again)]
    assert owner.inbox(a)['items']==[]


def test_inbox_excludes_historical_declined_inactive_and_banned(services,monkeypatch):
    repo,owner,a,b,c,guitar,acquire=prepare(services,monkeypatch)
    old=acquire(b,'2019-01-01')
    assert owner.inbox(a)['items']==[]
    current=acquire(c)
    assert [x['id'] for x in owner.inbox(a)['items']]==[str(current)]
    row=next(x for x in owner.pending(a,guitar)['items'] if x['id']==str(current))
    owner.respond(a,guitar,current,{'stance':'negative','revision':row['revision'],'reason':'Still mine'})
    assert owner.inbox(a)['items']==[]
    fresh=acquire(b,'2025-03-01')
    with repo.connect() as con:con.execute("UPDATE users SET ban_status='silent_ban' WHERE id=?",(b,))
    assert owner.inbox(a)['items']==[]


def test_sparse_pages_keep_cursor_and_recheck_each_guitar_once():
    owner=CloudOwner(None,None)
    owner.inbox_candidates=Mock(return_value=[{'id':i,'individual_id':1,'manufacturer':'Fixture','model':'Guitar'} for i in range(1,52)])
    owner.pending=Mock(return_value={'items':[],'can_write':True})
    assert owner.inbox('canonical')=={'items':[],'next_after':'50'}
    owner.pending.assert_called_once_with('canonical',1)


def test_inbox_route_uses_verified_canonical_actor_and_rejects_input():
    verifier,service=Mock(),Mock()
    verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True)
    verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical'}
    service.inbox.return_value={'items':[],'next_after':None}
    app=FastAPI();app.include_router(owner_router(verifier,service))
    with TestClient(app) as client:
        base='/api/auth/owner-acquire-requests';headers={'Authorization':'Bearer synthetic'}
        assert client.get(base).status_code==401
        assert client.get(base+'?after=9007199254740993',headers=headers).status_code==200
        service.inbox.assert_called_once_with('canonical',9007199254740993)
        for query in ('?actor=other','?after=0','?after=1&after=2','?after=9223372036854775808'):
            assert client.get(base+query,headers=headers).status_code==400
        service.inbox.side_effect=ServiceRestricted()
        assert client.get(base,headers=headers).status_code==403
