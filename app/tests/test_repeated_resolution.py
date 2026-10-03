import pytest
from fastapi.testclient import TestClient
from ygc import config
from ygc.db.repository import Repository, utcnow
from ygc.web import app, CONSOLE_ADMIN_TOKEN


def seed(repo, model, owner='Owner', serial='123456'):
    uid = repo.create_user(owner)
    iid, _, cid, _ = repo.create_initial_listing_claim(
        uid, manufacturer='Fender', model=model, serial_number=serial,
        media_storage_path='media/test.jpg')
    return uid, iid, cid


@pytest.fixture
def repo(tmp_path):
    r = Repository(tmp_path/'test.sqlite')
    r.init_db()
    return r


def test_merge_preserves_evidence_and_requires_approval_for_incoming_owner(repo):
    u1, first, listing = seed(repo, 'Stratocaster')
    u2, second, other = seed(repo, 'Strat', 'Second Owner')
    with repo.connect() as con:
        con.execute('UPDATE users SET signature_individual_id=? WHERE id=?', (second,u2))
        before = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                  for t in ('observations','claims','media_assets','claim_listing_items','claim_evidence')}
    assert repo.stats()['repeated_individuals'] == 1
    assert repo.repeated_groups()['total'] == 1
    repo.resolve_repeated(first,[first,second],'merge')
    with repo.connect() as con:
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        for t,n in before.items():
            assert con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] == n
        assert con.execute("SELECT COUNT(*) FROM claims WHERE claim_type='listing' AND status='active'").fetchone()[0] == 1
        row = con.execute('SELECT * FROM claims WHERE id=?',(other,)).fetchone()
        assert (row['claim_type'],row['verification_status']) == ('ownership','unverified')
        assert con.execute('SELECT current_owner_user_id FROM individuals').fetchone()[0] == u1
        assert con.execute('SELECT signature_individual_id FROM users WHERE id=?',(u2,)).fetchone()[0] == first
    assert repo.unverified_acquires()['items'][0]['claim_id'] == other
    repo.admin_moderate_claim(other,'positive')
    with repo.connect() as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals').fetchone()[0] == u2
    assert repo.stats()['repeated_individuals'] == 0
    repo.init_db()
    assert repo.repeated_groups()['total'] == 0


def test_delete_can_keep_any_member_and_validates_stale_groups(repo):
    _, a, _ = seed(repo,'A')
    _, b, _ = seed(repo,'B')
    u,c,_ = seed(repo,'C')
    with pytest.raises(ValueError,match='changed'):
        repo.resolve_repeated(a,[a,b],'delete')
    with repo.connect() as con:
        con.execute('UPDATE users SET signature_individual_id=? WHERE id=?',(c,u))
    repo.resolve_repeated(b,[a,b,c],'delete')
    with repo.connect() as con:
        assert [r[0] for r in con.execute('SELECT id FROM individuals')] == [b]
        assert con.execute('SELECT signature_individual_id FROM users WHERE id=?',(u,)).fetchone()[0] is None
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
    _, different, _ = seed(repo,'D',serial='999')
    with pytest.raises(ValueError):
        repo.resolve_repeated(b,[b,different],'merge')


def test_merge_rolls_back_on_rebuild_failure(repo,monkeypatch):
    _,a,_ = seed(repo,'A')
    _,b,_ = seed(repo,'B')
    def fail(*args):
        raise ValueError('test failure')
    monkeypatch.setattr(repo,'_rebuild_individual_snapshot_in_connection',fail)
    with pytest.raises(ValueError):
        repo.resolve_repeated(a,[a,b],'merge')
    assert repo.repeated_groups()['total'] == 1
    with repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM claims WHERE claim_type='listing'").fetchone()[0] == 2
        assert con.execute('SELECT COUNT(*) FROM individual_resolution_actions').fetchone()[0] == 0


def test_pending_filters_same_owner_and_history_without_writing(repo):
    user, iid, listing = seed(repo,'A')
    other = repo.create_user('Other')
    with repo.connect() as con:
        con.execute("UPDATE claims SET occurred_at='2020-01-01' WHERE id=?",(listing,))
        for uid,date in ((other,'2010-01-01'),(user,'2030-01-01'),(other,'2040-01-01')):
            cur=con.execute("INSERT INTO claims (individual_id,author_user_id,claim_type,ownership_kind,value_text,verification_status,occurred_at,created_at,updated_at) VALUES (?,?,'ownership','acquire',?,'unverified',?,?,?)",
                            (iid,uid,str(uid),date,utcnow(),utcnow()))
            con.execute("INSERT INTO claim_source_evidence (claim_id,evidence_type,effective_date,date_basis,created_at) VALUES (?,'acquisition_date',?,'user_reported',?)",
                        (cur.lastrowid,date,utcnow()))
        before = list(con.iterdump())
    result=repo.unverified_acquires(limit=1)
    assert result['total'] == 1
    assert result['items'][0]['occurred_at'] == '2040-01-01'
    with repo.connect() as con:
        assert list(con.iterdump()) == before


def test_repeated_endpoints_require_admin(repo,monkeypatch):
    monkeypatch.setattr(config,'DB_PATH',repo.db_path)
    _,a,_=seed(repo,'A')
    _,b,_=seed(repo,'B')
    body={'keep_id':b,'member_ids':[a,b],'action':'merge'}
    with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',45000)) as client:
        assert client.get('/api/admin/repeated').status_code == 403
        assert client.post('/api/admin/repeated/resolve',json=body).status_code == 403
        headers={'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}
        assert client.get('/api/admin/repeated',headers=headers).json()['total']==1
        assert client.post('/api/admin/repeated/resolve',headers=headers,json=body).status_code==200


def test_pending_pair_evaluates_release_together(repo):
    user,iid,listing=seed(repo,'A')
    other=repo.create_user('Earlier Owner')
    with repo.connect() as con:
        con.execute("UPDATE claims SET occurred_at='2020-01-01' WHERE id=?",(listing,))
        for kind,date in (('acquire','2010-01-01'),('release','2015-01-01')):
            con.execute("INSERT INTO claims (individual_id,author_user_id,claim_type,ownership_kind,ownership_source,ownership_pair_id,value_text,verification_status,occurred_at,created_at,updated_at) VALUES (?,?,'ownership',?,'former_owner','test-pair',?,'unverified',?,?,?)",
                        (iid,other,kind,str(other),date,utcnow(),utcnow()))
    assert repo.unverified_acquires()['total']==0


def test_pending_claims_without_request_keeps_legacy_and_excludes_request(repo):
    _, iid, _ = seed(repo, 'Stratocaster')
    other = repo.create_user('Other')
    with repo.connect() as con:
        cur = con.execute("INSERT INTO claims (individual_id,author_user_id,claim_type,ownership_kind,value_text,verification_status,occurred_at,created_at,updated_at) VALUES (?,?,'ownership','acquire',?,'unverified','2026-10-03',?,?)", (iid,other,str(other),utcnow(),utcnow()))
        claim_id = cur.lastrowid
        con.execute("INSERT INTO claim_source_evidence (claim_id,evidence_type,effective_date,date_basis,created_at) VALUES (?,'acquisition_date','2026-10-03','user_reported',?)", (claim_id,utcnow()))
    assert repo.unverified_acquires(without_request=True)['total'] == 1
    with repo.connect() as con:
        con.execute("INSERT INTO acquire_applications (revision,applicant_id,individual_id,original_individual_id,serial,challenge,expires_at,created_at,prompt_version,status,claim_id) VALUES ('test',?,?,?,'123456','TEST',0,?,'test','accepted',?)", (other,iid,iid,utcnow(),claim_id))
        before = list(con.iterdump())
    assert repo.unverified_acquires()['total'] == 1
    assert repo.unverified_acquires(without_request=True)['total'] == 0
    with repo.connect() as con:
        assert list(con.iterdump()) == before
