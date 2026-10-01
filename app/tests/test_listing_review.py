import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from ygc import acquire_review as ar, listing_review as lr, config, direct_experiment
from ygc.db.repository import Repository
from ygc.web import app
from authentication_fixtures import image_bytes,transcription


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(config,'DB_PATH',tmp_path/'listing.db')
    repo=Repository(config.DB_PATH);repo.init_db()
    return repo,repo.create_user('A'),repo.create_user('B')


def payload(**overrides):
    return dict(manufacturer='Fender',serial_number='SERIAL-123',model='Tele',finish='Black',year='2020',occurred_at='2026-01-01',**overrides)


def submit(setup,user=None):
    repo,a,b=setup;user=user or a
    row=lr.start(repo,user,payload());return lr.submit(repo,user,row['revision'],image_bytes(),image_bytes())


def review(repo,job):
    with repo.connect() as con:r=ar.find(con,job['revision'])
    key={k:job[k] for k in ('revision','lease_token')}
    ar.call_tool(repo,'ygc_listing_product_details',dict(**key,observations={k:'overview: テスト観察・確認不能' for k in ('maker','model','finish')}))
    return dict(**key,closeup=transcription(r['serial'],r['challenge']),overview=transcription(None,r['challenge']),identity=None,
        product_consistency={k:dict(status='uncertain',note='未確認は矛盾ではない') for k in ('maker','model','finish')})


def detail(repo,revision,user):
    with repo.connect() as con:return ar.detail(con,revision,user)


def test_listing_creates_nothing_until_review_then_initial_owner_and_reference(setup):
    repo,a,b=setup;r=submit(setup)
    with repo.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM individuals').fetchone()[0]==0
        assert con.execute('SELECT COUNT(*) FROM claims').fetchone()[0]==0
    assert ar.call_tool(repo,'ygc_pending_acquire',{})['jobs']==[]
    job=ar.call_tool(repo,'ygc_pending_listing',{})['jobs'][0]
    assert set(job['images'])=={'closeup','overview'} and not job['reference_available']
    assert 'SERIAL-123' not in json.dumps(job)
    data=review(repo,job)
    done=ar.call_tool(repo,'ygc_submit_listing_review',data)
    assert ar.call_tool(repo,'ygc_submit_listing_review',data)==done
    row=detail(repo,r['revision'],a);i=row['individual_id']
    assert row['status']=='accepted' and row['verification_status']=='positive'
    assert row['result']['comparison'] is None
    assert row['result']['adjudication']['rule_version']==lr.RULE_VERSION
    assert repo.get_individual(i)[0]['current_owner_user_id']==a
    assert len(repo.list_claims(i))==1
    with pytest.raises(ValueError):repo.set_claim_response(row['claim_id'],a,'negative')
    acquire=ar.start(repo,b,i)
    acquire=ar.submit(repo,b,acquire['revision'],'2026-02-01','',image_bytes(),image_bytes())
    assert acquire['reference_source']['kind']=='review'
    assert acquire['reference_source']['claim_id']==row['claim_id']
    client=TestClient(app)
    assert client.get('/api/acquire-applications/'+r['revision']+'/images/closeup').status_code==403
    with repo.connect() as con:media=con.execute('SELECT media_asset_id FROM claim_evidence WHERE claim_id=?',(row['claim_id'],)).fetchone()[0]
    assert client.get('/api/media/'+str(media)).status_code==200


@pytest.mark.parametrize('failure',['serial','challenge','finish'])
def test_listing_rejection_leaves_no_individual(setup,failure):
    repo,a,b=setup;r=submit(setup);job=ar.call_tool(repo,'ygc_pending_listing',{})['jobs'][0];data=review(repo,job)
    if failure=='finish':data['product_consistency']['finish']=dict(status='contradicted',note='明確な矛盾')
    else:data['closeup'][failure]['text']='WRONG'
    assert ar.call_tool(repo,'ygc_submit_listing_review',data)['status']=='rejected'
    with repo.connect() as con:assert con.execute('SELECT COUNT(*) FROM individuals').fetchone()[0]==0


def test_duplicates_ignore_model_and_race_cannot_create_two_individuals(setup):
    repo,a,b=setup;r1=submit(setup);r2=submit(setup,b)
    j1=ar.call_tool(repo,'ygc_pending_listing',{})['jobs'][0]
    j2=ar.call_tool(repo,'ygc_pending_listing',{})['jobs'][0]
    d1=review(repo,j1);d2=review(repo,j2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda d:ar.call_tool(repo,'ygc_submit_listing_review',d),[d1,d2]))
    assert sorted(r['status'] for r in results)==['accepted','closed']
    with repo.connect() as con:assert con.execute('SELECT COUNT(*) FROM individuals').fetchone()[0]==1
    request=payload();request.update(model='Different',manufacturer='FENDER',serial_number='SERIAL123')
    result=lr.start(repo,b,request)
    assert result['status']=='duplicate' and len(result['existing_individual_ids'])==1


def test_missing_image_or_cancel_and_old_route_do_not_bypass_review(setup):
    repo,a,b=setup
    client=TestClient(app)
    assert client.post('/api/users/'+str(a)+'/new-guitar').status_code==409
    assert client.post('/api/listing-applications',json=payload()).status_code==401
    r=lr.start(repo,a,payload())
    with pytest.raises(ValueError):lr.submit(repo,a,r['revision'],b'bad',image_bytes())
    assert detail(repo,r['revision'],a)['status']=='draft'
    lr.submit(repo,a,r['revision'],image_bytes(),image_bytes());job=ar.call_tool(repo,'ygc_pending_listing',{})['jobs'][0];data=review(repo,job)
    ar.action(repo,a,r['revision'],'cancel')
    with pytest.raises(ValueError):ar.call_tool(repo,'ygc_submit_listing_review',data)
    with repo.connect() as con:assert con.execute('SELECT COUNT(*) FROM individuals').fetchone()[0]==0


def test_ban_and_submission_deadline_and_listing_tool_isolation(setup):
    repo,a,b=setup;r=lr.start(repo,a,payload())
    with repo.connect() as con:con.execute('UPDATE acquire_applications SET expires_at=0 WHERE revision=?',(r['revision'],))
    with pytest.raises(ValueError):lr.submit(repo,a,r['revision'],image_bytes(),image_bytes())
    # Reading the history expires the draft in its own committed transaction.
    ar.list_for(repo,a);r=submit(setup);job=ar.call_tool(repo,'ygc_pending_listing',{})['jobs'][0]
    data=review(repo,job)
    with pytest.raises(ValueError,match='種別'):ar.call_tool(repo,'ygc_submit_acquire_review',data)
    with repo.connect() as con:con.execute("UPDATE users SET ban_status='ban' WHERE id=?",(a,))
    assert ar.call_tool(repo,'ygc_submit_listing_review',data)['status']=='closed'


def test_listing_mcp_and_admin_override(setup):
    repo,a,b=setup;r=submit(setup)
    response=direct_experiment.call_tool('ygc_pending_listing',{})
    job=json.loads(response['content'][0]['text'])['jobs'][0];data=review(repo,job)
    data['closeup']['challenge']['text']='WRONG'
    direct_experiment.call_tool('ygc_submit_listing_review',data)
    with repo.connect() as con:version=ar.detail(con,r['revision'],None,True)['management_version']
    approved=ar.administer(repo,r['revision'],'accept','目視確認',version)
    assert approved['status']=='accepted' and approved['verification_status']=='positive'
    rejected=ar.administer(repo,r['revision'],'reject','判定訂正',approved['management_version'])
    assert rejected['verification_status']=='negative' and rejected['result']['adjudication']['accepted'] is False
    approved=ar.administer(repo,r['revision'],'accept','再確認',rejected['management_version'])
    assert approved['claim_id']==rejected['claim_id']


@pytest.mark.parametrize('serial',['UNKNOWN','不明','---',''])
def test_unknown_serial_cannot_start_listing(setup,serial):
    repo,a,b=setup;data=payload();data['serial_number']=serial
    with pytest.raises(ValueError):lr.start(repo,a,data)


def test_listing_start_response_is_private_and_uses_actor(setup):
    repo,a,b=setup;client=TestClient(app)
    response=client.post('/api/listing-applications?viewer_id='+str(a),json=payload())
    assert response.status_code==200 and 'no-store' in response.headers['cache-control']
    row=response.json()
    assert row['original_individual_id'] is None
    with pytest.raises(PermissionError):lr.submit(repo,b,row['revision'],image_bytes(),image_bytes())


def test_jpg_upload_with_mpf_metadata_is_accepted(setup):
    import io
    from PIL import Image
    repo,a,b=setup;row=lr.start(repo,a,payload())
    buffer=io.BytesIO()
    Image.new('RGB',(120,80),'red').save(buffer,format='MPO',save_all=True,
        append_images=[Image.new('RGB',(30,20),'gray')])
    client=TestClient(app)
    response=client.post('/api/acquire-applications/'+row['revision']+'/submit?viewer_id='+str(a),
        data={'acquisition_date':'2026-01-01','body':''},
        files={'closeup':('closeup.jpg',buffer.getvalue(),'image/jpeg'),
               'overview':('overview.jpg',buffer.getvalue(),'image/jpeg')})
    assert response.status_code==200
    assert response.json()['status']=='pending'
    assert response.json()['images']['overview']['dimensions']==[120,80]
