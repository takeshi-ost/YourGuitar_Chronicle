import json
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from ygc import acquire_review as ar, config, direct_experiment
from ygc.db.repository import Repository
from ygc.web import app, CONSOLE_ADMIN_TOKEN
from authentication_fixtures import image_bytes, transcription, comparison


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'chronicle.db')
    repo=Repository(config.DB_PATH);repo.init_db()
    a=repo.create_user('A');b=repo.create_user('B');c=repo.create_user('C')
    (tmp_path/'reference.png').write_bytes(image_bytes())
    individual,*_=repo.create_initial_listing_claim(a,manufacturer='Fender',model='Tele',serial_number='ISSB25003873',media_storage_path='reference.png',occurred_at='2026-01-01')
    return repo,a,b,c,individual


def attach_reverb_evidence(con,individual):
    listing=con.execute("SELECT id FROM claims WHERE individual_id=? AND claim_type='listing'",(individual,)).fetchone()[0]
    con.execute("""INSERT INTO claim_source_evidence(claim_id,evidence_type,source_site,source_listing_id,payload_json,created_at)
        VALUES (?,'marketplace_listing','reverb',?,?,'2026-01-01')""",
        (listing,str(individual),json.dumps({'provenance':{'image_url':'https://images.reverb.com/test.jpg'}})))


def submitted(setup,user=None):
    repo,a,b,c,i=setup;user=user or b
    r=ar.start(repo,user,i)
    return ar.submit(repo,user,r['revision'],'2026-02-01','test',image_bytes(),image_bytes())


def claim(repo):return ar.call_tool(repo,'ygc_pending_acquire',{})['jobs'][0]


def review(repo,job):
    with repo.connect() as con:r=ar.find(con,job['revision'])
    if r['status']=='processing':
        ar.call_tool(repo,'ygc_acquire_product_details',dict(revision=job['revision'],lease_token=job['lease_token'],
            observations={k:'overview: 確認不能（テスト用観察）' for k in ('maker','model','finish')}))
    return dict(revision=job['revision'],lease_token=job['lease_token'],closeup=transcription(r['serial'],r['challenge']),
      overview=transcription(None,r['challenge']),identity=comparison()['identity'] if job['reference_available'] else None,
      product_consistency={k:dict(status='uncertain',note='画像からの確認不能。矛盾とは扱わない。') for k in ('maker','model','finish')})


def complete(repo,job):return ar.call_tool(repo,'ygc_submit_acquire_review',review(repo,job))


def detail(repo,revision,user):
    with repo.connect() as con:return ar.detail(con,revision,user)


def test_owner_approval_and_private_evidence(setup):
    repo,a,b,c,i=setup
    before=len(repo.list_claims(i));r=submitted(setup)
    assert len(repo.list_claims(i))==before
    job=claim(repo)
    assert 'ISSB25003873' not in json.dumps(job)
    assert ar.call_tool(repo,'ygc_acquire_image',dict(revision=job['revision'],lease_token=job['lease_token'],role='reference'))['content'][0]['type']=='image'
    with pytest.raises(PermissionError):detail(repo,r['revision'],a)
    with pytest.raises(PermissionError):detail(repo,r['revision'],c)
    done=complete(repo,job)
    assert done['status']=='accepted'
    assert detail(repo,r['revision'],a)['verification_status']=='unverified'
    assert repo.get_individual(i)[0]['current_owner_user_id']==a
    assert len(repo.list_claims(i))==before+1
    assert complete(repo,job)==done
    assert len(repo.list_claims(i))==before+1
    repo.set_claim_response(done['claim_id'],a,stance='positive')
    assert repo.get_individual(i)[0]['current_owner_user_id']==b
    with pytest.raises(PermissionError):detail(repo,r['revision'],a)
    assert detail(repo,r['revision'],b)['result']['adjudication']['accepted'] is True


def test_unknown_owner_no_reference_waives_only_identity(setup):
    repo,a,b,c,i=setup
    repo.create_ownership_claim(a,i,ownership_kind='release',occurred_at='2026-01-02')
    r=submitted(setup);job=claim(repo)
    assert not job['reference_available']
    payload=review(repo,job);payload['closeup']['challenge']['text']='WRONG'
    ar.call_tool(repo,'ygc_submit_acquire_review',payload)
    rejected=detail(repo,r['revision'],b)
    assert rejected['status']=='rejected' and rejected['claim_id'] is None
    r=submitted(setup);job=claim(repo);complete(repo,job)
    accepted=detail(repo,r['revision'],b)
    assert accepted['status']=='accepted'
    assert accepted['result']['comparison'] is None
    assert '比較画像なし' in accepted['report']
    assert repo.get_individual(i)[0]['current_owner_user_id']==b


def test_dead_reference_is_not_absence(setup,monkeypatch):
    repo,a,b,c,i=setup
    (config.DATA_DIR/'reference.png').unlink()
    with pytest.raises(ValueError,match='画像なし扱い'):submitted(setup)
    assert ar.list_for(repo,b)[0]['status']=='draft'


def test_timeout_submit_expiry_and_cancellation(setup,monkeypatch):
    repo,a,b,c,i=setup;r=ar.start(repo,b,i)
    assert ar.start(repo,b,i)['revision']==r['revision']
    with repo.connect() as con:con.execute('UPDATE acquire_applications SET expires_at=0 WHERE revision=?',(r['revision'],))
    assert ar.list_for(repo,b)[0]['status']=='expired'
    r=submitted(setup);job=claim(repo)
    with repo.connect() as con:con.execute('UPDATE acquire_applications SET expires_at=0 WHERE revision=?',(r['revision'],))
    complete(repo,job) # Submission deadline does not expire a queued review.
    r=submitted(setup,c);job=claim(repo)
    ar.action(repo,c,r['revision'],'cancel')
    with pytest.raises(ValueError):complete(repo,job)


def test_transfer_during_review_closes_without_claim(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo)
    # Ownership changes atomically through the existing Transfer path.
    transfer=repo.create_transfer(a,i,b)
    repo.resolve_transfer(transfer,b,'accept')
    before=len(repo.list_claims(i));done=complete(repo,job)
    assert done['status']=='closed' and done['claim_id'] is None
    assert len(repo.list_claims(i))==before
    assert 'Current Owner' in detail(repo,r['revision'],b)['error']


def test_concurrent_claims_and_results_are_idempotent(setup):
    repo,a,b,c,i=setup;submitted(setup)
    with ThreadPoolExecutor(max_workers=2) as pool:claims=list(pool.map(lambda _:ar.call_tool(repo,'ygc_pending_acquire',{}),range(2)))
    jobs=[j for response in claims for j in response['jobs']];assert len(jobs)==1
    payload=review(repo,jobs[0])
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:ar.call_tool(repo,'ygc_submit_acquire_review',payload),range(2)))
    assert results[0]==results[1]


def test_api_rejects_legacy_acquire_and_protects_images(setup):
    repo,a,b,c,i=setup;client=TestClient(app,base_url='http://localhost',client=('127.0.0.1',1))
    response=client.post(f'/api/individuals/{i}/ownership-claim',json={'user_id':b,'ownership_kind':'acquire','occurred_at':'2026-02-01'})
    assert response.status_code==409
    assert client.post(f'/api/individuals/{i}/acquire-applications').status_code==401
    r=submitted(setup);url=f"/api/acquire-applications/{r['revision']}/images/closeup"
    assert client.get(url).status_code==403
    assert client.get(url,params={'viewer_id':c}).status_code==403
    assert client.get(url,params={'viewer_id':b}).status_code==200
    assert client.get(url,headers={'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}).status_code==200


def test_current_owner_and_unknown_serial_cannot_apply(setup):
    repo,a,b,c,i=setup
    with pytest.raises(ValueError,match='Current Owner'):ar.start(repo,a,i)
    with repo.connect() as con:con.execute('UPDATE individuals SET serial_number=NULL WHERE id=?',(i,))
    with pytest.raises(ValueError,match='シリアル不明'):ar.start(repo,b,i)


def test_ban_and_reference_invalidation_close_without_acquire(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo)
    with repo.connect() as con:con.execute("UPDATE users SET ban_status='ban' WHERE id=?",(b,))
    assert complete(repo,job)['status']=='closed'
    assert len(repo.list_claims(i))==1


def test_production_mcp_routes_to_main_database(setup):
    repo,a,b,c,i=setup;submitted(setup)
    result=direct_experiment.call_tool('ygc_pending_acquire',{})
    job=json.loads(result['content'][0]['text'])['jobs'][0]
    result=direct_experiment.call_tool('ygc_submit_acquire_review',review(repo,job))
    assert json.loads(result['content'][0]['text'])['status']=='accepted'


def test_past_acquire_keeps_current_owner_and_creates_former_history(setup):
    repo,a,b,c,i=setup;r=ar.start(repo,b,i)
    ar.submit(repo,b,r['revision'],'2025-01-01','',image_bytes(),image_bytes())
    done=complete(repo,claim(repo));repo.set_claim_response(done['claim_id'],a,'positive')
    assert repo.get_individual(i)[0]['current_owner_user_id']==a
    _,guitars=repo.get_user(b)
    assert next(g for g in guitars if g['individual_id']==i)['ownership_status']=='former_owner'


def test_owner_changed_to_third_party_requires_new_current_owner(setup):
    repo,a,b,c,i=setup;submitted(setup);job=claim(repo)
    transfer=repo.create_transfer(a,i,c);repo.resolve_transfer(transfer,c,'accept')
    done=complete(repo,job)
    assert detail(repo,job['revision'],b)['verification_status']=='unverified'
    assert repo.get_individual(i)[0]['current_owner_user_id']==c
    assert repo.set_claim_response(done['claim_id'],c,'positive')


def test_reviewer_error_is_not_rejection_and_stale_lease_cannot_submit(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo)
    ar.call_tool(repo,'ygc_fail_acquire',dict(revision=job['revision'],lease_token=job['lease_token'],reason='画像が見えません'))
    d=detail(repo,r['revision'],b)
    assert d['status']=='error' and d['result'] is None and d['claim_id'] is None
    ar.action(repo,b,r['revision'],'retry');next_job=claim(repo)
    with pytest.raises(ValueError):complete(repo,job)
    assert complete(repo,next_job)['status']=='accepted'


def test_deleted_individual_closes_application(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo)
    # Exercise the same SET NULL boundary used when a Merge deletes its source.
    with repo.connect() as con:
        con.execute('DELETE FROM observations WHERE individual_id=?',(i,))
        con.execute('DELETE FROM individuals WHERE id=?',(i,))
    assert complete(repo,job)['status']=='closed'
    assert detail(repo,r['revision'],b)['claim_id'] is None


def test_snapshot_does_not_include_new_arrivals(setup):
    repo,a,b,c,i=setup;submitted(setup)
    snapshot=ar.call_tool(repo,'ygc_pending_acquire',{})
    submitted(setup,c)
    assert ar.call_tool(repo,'ygc_pending_acquire',{'remaining_revisions':snapshot['remaining_revisions']})['jobs']==[]
    assert len(ar.call_tool(repo,'ygc_pending_acquire',{})['jobs'])==1


def test_reference_and_serial_changes_require_resubmission(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo)
    with repo.connect() as con:con.execute("UPDATE individuals SET serial_number='CHANGED' WHERE id=?",(i,))
    assert complete(repo,job)['status']=='closed'


def test_formal_evidence_survives_experiment_queue_deletion(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo);complete(repo,job)
    exp=direct_experiment.prepare('unrelated','ABC123','TEST1234',[image_bytes()]*3)
    direct_experiment.manage(exp['revision'],'cancel');direct_experiment.manage(exp['revision'],'delete')
    assert detail(repo,r['revision'],b)['report']
    with repo.connect() as con:assert json.loads(ar.find(con,r['revision'])['images'])['overview']


def test_owner_approval_wait_deduplicates_new_applications(setup):
    repo,a,b,c,i=setup;r=submitted(setup);complete(repo,claim(repo))
    assert ar.start(repo,b,i)['revision']==r['revision']


def test_three_expired_leases_stop_and_preserve_history(setup):
    repo,a,b,c,i=setup;r=submitted(setup)
    for _ in range(3):
        job=claim(repo)
        with repo.connect() as con:con.execute('UPDATE acquire_applications SET lease_until=0 WHERE revision=?',(r['revision'],))
        ar.list_for(repo,b)
    d=detail(repo,r['revision'],b)
    assert d['status']=='error' and d['result'] is None
    assert sum(e['kind']=='timeout' for e in d['events'])==3
    ar.action(repo,b,r['revision'],'retry')
    assert complete(repo,claim(repo))['status']=='accepted'


def test_actual_merge_closes_pending_source_and_preserves_formal_evidence(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo)
    other,*_=repo.create_initial_listing_claim(c,manufacturer='Fender',model='Telecaster',serial_number='ISSB25003873',media_storage_path='reference.png',occurred_at='2026-01-02')
    # Same model/serial may resolve to an existing individual; use a distinct model.
    if other==i:
        other,*_=repo.create_initial_listing_claim(c,manufacturer='Fender',model='Tele Custom',serial_number='ISSB25003873',media_storage_path='reference.png',occurred_at='2026-01-02')
    repo.resolve_repeated(other,[other,i],'merge')
    assert complete(repo,job)['status']=='closed'
    assert detail(repo,r['revision'],b)['images']['closeup']


def test_reverb_url_failure_is_not_waived(setup,monkeypatch):
    import httpx
    repo,a,b,c,i=setup
    repo.create_ownership_claim(a,i,ownership_kind='release',occurred_at='2026-01-02')
    with repo.connect() as con:
        attach_reverb_evidence(con,i)
    client=httpx.Client
    monkeypatch.setattr(ar.httpx,'Client',lambda **kw:client(transport=httpx.MockTransport(lambda request:httpx.Response(404)),**kw))
    with pytest.raises(ValueError,match='取得できません'):submitted(setup)
    assert ar.list_for(repo,b)[0]['status']=='draft'
    monkeypatch.setattr(ar.httpx,'Client',lambda **kw:client(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=image_bytes())),**kw))
    submitted(setup);job=claim(repo)
    assert job['reference_available'] is True
    assert complete(repo,job)['status']=='accepted'


def test_unapproved_reference_hosts_and_redirects_do_not_fetch():
    for url in ('http://images.reverb.com/a','https://127.0.0.1/a','https://images.reverb.com.evil.example/a'):
        with pytest.raises(ValueError,match='URL'):ar.reference_bytes({'kind':'reverb','url':url},None)


def test_uncertain_dark_reflective_guitar_passes_and_still_waits_for_owner(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo);payload=review(repo,job)
    payload['identity'].update(status='uncertain',supporting_features=[],differences=[],
        comparison_coverage='insufficient',ambiguous_differences=[
            {'location':'B/C ボディ','observation':'反射と濃い塗装で個体の一致を確認できない'}])
    response=ar.call_tool(repo,'ygc_submit_acquire_review',payload)
    d=detail(repo,r['revision'],b)
    assert response['status']=='accepted' and d['verification_status']=='unverified'
    assert repo.get_individual(i)[0]['current_owner_user_id']==a
    assert d['result']['comparison']['identity']['status']=='uncertain'
    assert d['result']['adjudication']['rule_version']==ar.RULE_VERSION
    assert '同一個体の確証は得られていません' in d['report']


def test_clear_individual_contradiction_still_rejects_acquire(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo);payload=review(repo,job)
    payload['identity'].update(status='contradicted',supporting_features=[],differences=[
        {'location':'B/C 左側ボディ','observation':'片方にはf字孔があり、もう一方の同位置にはない'}])
    response=ar.call_tool(repo,'ygc_submit_acquire_review',payload)
    d=detail(repo,r['revision'],b)
    assert response['status']=='rejected' and d['claim_id'] is None
    assert 'clear_contradiction' in d['result']['adjudication']['reason_codes']


def test_product_observations_precede_disclosure_and_are_immutable(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo)
    assert 'Fender' not in json.dumps(job)
    key=dict(revision=job['revision'],lease_token=job['lease_token'])
    args=dict(**key,observations={k:'overview: 確認不能' for k in ('maker','model','finish')})
    response=direct_experiment.call_tool('ygc_acquire_product_details',args)
    data=json.loads(response['content'][0]['text'])
    assert data['product_details']==dict(maker='Fender',model='Tele',finish=None)
    assert r['serial'] not in json.dumps(data) and r['challenge'] not in json.dumps(data)
    assert ar.call_tool(repo,'ygc_acquire_product_details',args)==data
    args['observations']['maker']='開示後に変更'
    with pytest.raises(ValueError,match='変更できません'):ar.call_tool(repo,'ygc_acquire_product_details',args)


@pytest.mark.parametrize('field',['maker','model','finish'])
def test_clear_product_contradiction_rejects_without_reference(setup,field):
    repo,a,b,c,i=setup
    repo.create_specification_claim(a,i,field_name='finish',value_text='Sunburst',occurred_at='2026-01-01')
    repo.create_ownership_claim(a,i,ownership_kind='release',occurred_at='2026-01-02')
    r=submitted(setup);job=claim(repo);payload=review(repo,job)
    assert not job['reference_available']
    payload['product_consistency'][field]=dict(status='contradicted',note='overviewの指定部位に明確な矛盾（テスト用）')
    result=ar.call_tool(repo,'ygc_submit_acquire_review',payload)
    assert result['status']=='rejected' and result['claim_id'] is None
    d=detail(repo,r['revision'],b)['result']
    assert d['adjudication']['reason_codes']==['product_'+field+'_contradiction']
    assert d['product_consistency']['finish']['registered']=='Sunburst'


def test_missing_registered_finish_is_not_a_contradiction(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo);payload=review(repo,job)
    payload['product_consistency']['finish']=dict(status='contradicted',note='登録値が空')
    assert ar.call_tool(repo,'ygc_submit_acquire_review',payload)['status']=='accepted'
    result=detail(repo,r['revision'],b)['result']
    assert result['product_consistency']['finish']['status']=='not_registered'
    assert result['product_consistency']['maker']['status']=='uncertain'
    assert result['product_consistency']['maker']['observed'].startswith('overview:')


def test_product_check_cannot_be_omitted_or_sent_before_observations(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo);payload=review(repo,job)
    missing=dict(payload);missing.pop('product_consistency')
    with pytest.raises(ValueError,match='照合結果'):ar.call_tool(repo,'ygc_submit_acquire_review',missing)
    with repo.connect() as con:con.execute('UPDATE acquire_applications SET product_observations=NULL WHERE revision=?',(r['revision'],))
    with pytest.raises(ValueError,match='照合結果'):ar.call_tool(repo,'ygc_submit_acquire_review',payload)
    assert detail(repo,r['revision'],b)['status']=='processing'
    assert len(repo.list_claims(i))==1


def test_product_detail_uses_displayed_finish_and_detects_changes(setup):
    repo,a,b,c,i=setup
    repo.create_specification_claim(a,i,field_name='finish',value_text='Black',occurred_at='2026-01-01')
    r=submitted(setup);job=claim(repo);payload=review(repo,job)
    with repo.connect() as con:
        assert json.loads(ar.find(con,r['revision'])['product_details'])['finish']=='Black'
    repo.create_specification_claim(a,i,field_name='finish',value_text='Red',occurred_at='2026-01-02')
    assert ar.call_tool(repo,'ygc_submit_acquire_review',payload)['status']=='closed'
    assert '登録情報が変更' in detail(repo,r['revision'],b)['error']


def test_upgrade_preserves_old_result_and_initializes_queued_metadata(setup):
    repo,a,b,c,i=setup;r=submitted(setup)
    with repo.connect() as con:
        con.execute('ALTER TABLE acquire_applications DROP COLUMN product_details')
        con.execute('ALTER TABLE acquire_applications DROP COLUMN product_observations')
    repo.init_db();repo.init_db()
    job=claim(repo);payload=review(repo,job)
    assert ar.call_tool(repo,'ygc_submit_acquire_review',payload)['status']=='accepted'
    with repo.connect() as con:
        saved=json.loads(ar.find(con,r['revision'])['received']);saved.pop('product_consistency')
        con.execute('UPDATE acquire_applications SET received=?,prompt_version=? WHERE revision=?',
                    (json.dumps(saved),'acquire-evidence-v1',r['revision']))
    payload.pop('product_consistency')
    assert ar.call_tool(repo,'ygc_submit_acquire_review',payload)['status']=='accepted'


def test_retry_resets_blind_observations_and_requires_new_lease(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo);review(repo,job)
    with repo.connect() as con:con.execute('UPDATE acquire_applications SET lease_until=0 WHERE revision=?',(r['revision'],))
    new=claim(repo)
    with repo.connect() as con:assert ar.find(con,r['revision'])['product_observations'] is None
    with pytest.raises(ValueError,match='失効'):review(repo,job)
    assert complete(repo,new)['status']=='accepted'


@pytest.mark.parametrize('owner_kind',['unknown','source'])
@pytest.mark.parametrize('accepted',[True,False])
def test_automatic_positive_and_ownership_for_nonuser_owner(setup,monkeypatch,owner_kind,accepted):
    """Exercise result application, not AI accuracy; all records are in tmp_path."""
    import httpx
    repo,a,b,c,i=setup
    if owner_kind=='unknown':
        repo.create_ownership_claim(a,i,ownership_kind='release',occurred_at='2026-01-02')
    else:
        # Turn the fixture's listing author into an external source account.
        with repo.connect() as con:
            con.execute("UPDATE users SET account_type='source' WHERE id=?",(a,))
            attach_reverb_evidence(con,i)
        repo.rebuild_individual_snapshot(i)
        client=httpx.Client
        monkeypatch.setattr(ar.httpx,'Client',lambda **kw:client(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=image_bytes())),**kw))
    before_owner=repo.get_individual(i)[0]['current_owner_user_id']
    if owner_kind=='unknown':assert before_owner is None
    else:
        with repo.connect() as con:
            assert before_owner is None or con.execute('SELECT account_type FROM users WHERE id=?',(before_owner,)).fetchone()[0]=='source'
    before_count=len(repo.list_claims(i))
    r=submitted(setup);job=claim(repo)
    assert job['reference_available'] is (owner_kind=='source')
    assert repo.get_individual(i)[0]['current_owner_user_id']==before_owner
    assert len(repo.list_claims(i))==before_count
    payload=review(repo,job)
    if not accepted:payload['closeup']['challenge']['text']='WRONG'
    done=ar.call_tool(repo,'ygc_submit_acquire_review',payload)
    assert ar.call_tool(repo,'ygc_submit_acquire_review',payload)==done
    d=detail(repo,r['revision'],b)
    if not accepted:
        assert done['status']=='rejected' and done['claim_id'] is None
        assert len(repo.list_claims(i))==before_count
        assert repo.get_individual(i)[0]['current_owner_user_id']==before_owner
        return
    assert done['status']=='accepted'
    assert d['verification_status']=='positive'
    assert repo.get_individual(i)[0]['current_owner_user_id']==b
    assert len(repo.list_claims(i))==before_count+1
    _,guitars=repo.get_user(b)
    assert next(g for g in guitars if g['individual_id']==i)['ownership_status']=='current_owner'
    assert d['result']['adjudication']['accepted'] is True
    assert d['result']['product_consistency'] and d['report'] and d['images']['overview']
    with pytest.raises(ValueError):repo.set_claim_response(done['claim_id'],b,'negative')
    assert detail(repo,r['revision'],b)['verification_status']=='positive'
    with repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM notifications WHERE claim_id=? AND notification_type='claim_review'",(done['claim_id'],)).fetchone()[0]==0


def admin_change(repo,revision,operation,reason='管理者テスト'):
    with repo.connect() as con:version=ar.detail(con,revision,None,True)['management_version']
    return ar.administer(repo,revision,operation,reason,version)


def test_admin_overrides_preserve_ai_and_apply_owner_rules(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo);payload=review(repo,job)
    payload['closeup']['challenge']['text']='WRONG'
    ar.call_tool(repo,'ygc_submit_acquire_review',payload)
    original=detail(repo,r['revision'],b)['result']
    row=admin_change(repo,r['revision'],'accept')
    assert row['status']=='accepted' and row['verification_status']=='unverified'
    assert row['result']==original and row['admin_review']['accepted'] is True
    assert repo.get_individual(i)[0]['current_owner_user_id']==a
    claim_id=row['claim_id']
    assert admin_change(repo,r['revision'],'positive')['verification_status']=='positive'
    assert repo.get_individual(i)[0]['current_owner_user_id']==b
    with pytest.raises(ValueError):repo.set_claim_response(claim_id,b,'negative')
    row=admin_change(repo,r['revision'],'reject')
    assert row['status']=='rejected' and row['verification_status']=='negative'
    assert repo.get_individual(i)[0]['current_owner_user_id']==a
    assert row['result']==original
    row=admin_change(repo,r['revision'],'accept')
    assert row['claim_id']==claim_id and row['verification_status']=='unverified'
    assert len(repo.list_claims(i))==2
    assert row['events'][-1]['kind']=='admin_accept'


def test_admin_manual_accept_unknown_owner_and_stale_worker(setup):
    repo,a,b,c,i=setup
    repo.create_ownership_claim(a,i,ownership_kind='release',occurred_at='2026-01-02')
    r=submitted(setup);job=claim(repo);payload=review(repo,job)
    row=admin_change(repo,r['revision'],'accept')
    assert row['verification_status']=='positive' and row['result'] is None
    assert repo.get_individual(i)[0]['current_owner_user_id']==b
    assert row['admin_review']['accepted'] is True
    with pytest.raises(ValueError,match='失効'):ar.call_tool(repo,'ygc_submit_acquire_review',payload)
    row=admin_change(repo,r['revision'],'reject')
    assert repo.get_individual(i)[0]['current_owner_user_id'] is None


def test_admin_retry_archives_result_and_prevents_conflicting_application(setup):
    repo,a,b,c,i=setup;r=submitted(setup);job=claim(repo);payload=review(repo,job)
    payload['closeup']['challenge']['text']='WRONG';ar.call_tool(repo,'ygc_submit_acquire_review',payload)
    old=detail(repo,r['revision'],b)['result']
    second=ar.start(repo,b,i)
    with pytest.raises(ValueError,match='別申請'):admin_change(repo,r['revision'],'retry')
    ar.action(repo,b,second['revision'],'cancel')
    row=admin_change(repo,r['revision'],'retry')
    assert row['status']=='pending' and row['result'] is None
    archived=json.loads(row['events'][-1]['note'])['previous_review']['result']
    assert archived==old
    assert complete(repo,claim(repo))['status']=='accepted'


def test_admin_cancel_and_optimistic_lock(setup):
    repo,a,b,c,i=setup;r=submitted(setup)
    with repo.connect() as con:version=ar.detail(con,r['revision'],None,True)['management_version']
    job=claim(repo)
    with pytest.raises(ValueError,match='更新されています'):ar.administer(repo,r['revision'],'accept','test',version)
    row=admin_change(repo,r['revision'],'cancel')
    assert row['status']=='cancelled' and row['claim_id'] is None
    with pytest.raises(ValueError):complete(repo,job)


def test_admin_management_api_authorization_reason_and_version(setup):
    repo,a,b,c,i=setup;r=submitted(setup)
    with repo.connect() as con:version=ar.detail(con,r['revision'],None,True)['management_version']
    payload=dict(operation='accept',reason='目視確認',expected_version=version)
    client=TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',45000))
    url='/api/admin/acquire-applications/'+r['revision']+'/manage'
    assert client.post(url,json=payload).status_code==403
    headers={'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}
    assert client.post(url,json={**payload,'reason':' '},headers=headers).status_code==409
    assert client.post(url,json=payload,headers=headers).status_code==200
    assert client.post(url,json=payload,headers=headers).status_code==409
    assert len(repo.list_claims(i))==2
