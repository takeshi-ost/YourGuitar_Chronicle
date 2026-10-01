import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from ygc import direct_experiment as direct, direct_queue as queue, config
from ygc.web import app, CONSOLE_ADMIN_TOKEN
from authentication_fixtures import image_bytes, transcription, comparison


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)


def prepared(application_id='test-001'):
    return direct.prepare(application_id,'ISSB25003873','N3G8PQTS',[image_bytes()]*3)


def claim():
    return json.loads(direct.call_tool('ygc_pending_test',{})['content'][0]['text'])['jobs']


def review(job):
    return dict(application_id=job['application_id'],revision=job['revision'],lease_token=job['lease_token'],
                closeup=transcription(),overview=transcription(None),identity=comparison()['identity'])


def key(job,role='closeup'):
    return dict(application_id=job['application_id'],revision=job['revision'],lease_token=job['lease_token'],role=role)


def client():
    return TestClient(app,base_url='http://localhost',client=('127.0.0.1',1))


def expire(job):
    with queue.transaction() as db:
        db.execute('UPDATE jobs SET lease_until=0 WHERE revision=?',(job['revision'],))


def test_blind_images_and_idempotent_submission():
    prepared();job=claim()[0]
    assert 'ISSB25003873' not in json.dumps(job) and 'N3G8PQTS' not in json.dumps(job)
    for role in ('closeup','overview','reference'):
        image=direct.call_tool('ygc_test_image',key(job,role))
        assert image['content'][1]['type']=='image' and image['content'][1]['data']
    raw=review(job);reply=direct.call_tool('ygc_submit_test_review',raw)
    assert 'ISSB25003873' not in json.dumps(reply)
    assert direct.call_tool('ygc_submit_test_review',raw)==reply
    result=direct.status(job['revision'])
    assert result['result']['adjudication']['accepted'] is True
    assert 'ISSB25003873' in result['report_text']
    assert result['completed_at'] and result['started_at'] and result['created_at']
    assert 'lease_token' not in json.dumps(result)
    raw['overview']['challenge']['text']='DIFFERENT'
    with pytest.raises(ValueError):direct.call_tool('ygc_submit_test_review',raw)
    assert claim()==[]


def test_multiple_jobs_fifo_and_pending_deduplication():
    a=prepared('a');duplicate=prepared('a');b=prepared('b')
    assert a['revision']==duplicate['revision']
    assert a['token']==b['token']
    first=claim()[0];second=claim()[0]
    assert first['revision']==a['revision'] and second['revision']==b['revision']
    assert claim()==[]
    direct.call_tool('ygc_submit_test_review',review(first))
    direct.call_tool('ygc_submit_test_review',review(second))
    assert len(direct.status()['jobs'])==2
    assert all(j['status']=='completed' for j in direct.status()['jobs'])
    again=prepared('a');assert again['revision']!=a['revision']


def test_concurrent_claims_do_not_duplicate():
    for i in range(5):prepared(str(i))
    with ThreadPoolExecutor(max_workers=8) as pool:
        replies=list(pool.map(lambda _:claim(),range(8)))
    revisions=[reply[0]['revision'] for reply in replies if reply]
    assert len(revisions)==len(set(revisions))==5


def test_wrong_lease_wrong_revision_and_incomplete_output_do_not_reject():
    prepared();job=claim()[0]
    for field in ('lease_token','revision','application_id'):
        raw=review(job);raw[field]='wrong-wrong-wrong-wrong'
        with pytest.raises(ValueError):direct.call_tool('ygc_submit_test_review',raw)
    raw=review(job);del raw['identity']['comparison_coverage']
    with pytest.raises(ValueError):direct.call_tool('ygc_submit_test_review',raw)
    assert direct.status(job['revision'])['status']=='processing'
    assert direct.status(job['revision'])['result'] is None


def test_valid_mismatch_is_false():
    prepared();job=claim()[0];raw=review(job);raw['closeup']['serial']['text']='DIFFERENT'
    direct.call_tool('ygc_submit_test_review',raw)
    assert direct.status(job['revision'])['result']['adjudication']['accepted'] is False


def test_timeout_reclaims_and_rejects_stale_submission_then_stops_after_three():
    prepared();old=claim()[0];expire(old)
    new=claim()[0]
    assert new['revision']==old['revision'] and new['lease_token']!=old['lease_token']
    with pytest.raises(ValueError):direct.call_tool('ygc_submit_test_review',review(old))
    expire(new);third=claim()[0];expire(third)
    assert claim()==[]
    result=direct.status(third['revision']);assert result['status']=='error' and result['result'] is None
    assert len([e for e in result['events'] if e['kind']=='timeout'])==3
    direct.manage(third['revision'],'retry');assert claim()[0]['revision']==third['revision']


def test_fail_cancel_retry_delete_and_revocation_preserve_records():
    data=prepared();job=claim()[0]
    direct.call_tool('ygc_fail_test',dict(application_id=job['application_id'],revision=job['revision'],lease_token=job['lease_token'],reason='画像が見えない'))
    assert direct.status(job['revision'])['status']=='error'
    assert direct.status(job['revision'])['result'] is None
    direct.manage(job['revision'],'retry');new=claim()[0]
    direct.revoke();assert not direct.authorized(data['token'])
    assert direct.status(job['revision'])['status']=='pending'
    assert direct.connection()['token']!=data['token']
    with pytest.raises(ValueError):direct.call_tool('ygc_submit_test_review',review(new))
    direct.manage(job['revision'],'cancel');assert claim()==[]
    direct.manage(job['revision'],'delete');assert direct.status()['jobs']==[]


def test_persistence_across_processes_and_private_permissions():
    import os,subprocess,sys
    from pathlib import Path
    data=prepared();job=claim()[0];direct.call_tool('ygc_submit_test_review',review(job))
    env={**os.environ,'YGC_DATA_DIR':str(config.DATA_DIR),'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
    script="from ygc.direct_experiment import connection,status; import json; print(json.dumps({'connection':connection(),'status':status()}))"
    result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,env=env,check=True)
    restored=json.loads(result.stdout)
    assert restored['connection']['token']==data['token']
    assert restored['status']['jobs'][0]['status']=='completed'
    assert (config.DATA_DIR/'direct-review/queue.sqlite3').stat().st_mode&0o777==0o600
    assert (config.DATA_DIR/'direct-review').stat().st_mode&0o777==0o700


def test_mcp_http_roundtrip_and_boundary():
    data=prepared();c=client();url='/api/experiments/direct/mcp'
    msg={'jsonrpc':'2.0','id':1,'method':'initialize','params':{}}
    assert c.post(url,json=msg).status_code==401
    headers={'Authorization':'Bearer '+data['token']}
    assert c.post(url,json=msg,headers={**headers,'Origin':'https://evil.example'}).status_code==403
    remote=TestClient(app,base_url='http://localhost',client=('192.0.2.1',1))
    assert remote.post(url,json=msg,headers=headers).status_code==403
    assert c.post(url,json=msg,headers=headers).json()['result']['protocolVersion']==direct.PROTOCOL
    assert c.post(url,json={'jsonrpc':'2.0','method':'notifications/initialized'},headers=headers).status_code==202
    assert c.get(url,headers=headers).status_code==405
    msg.update(method='tools/list')
    tools=c.post(url,json=msg,headers=headers).json()['result']['tools']
    assert len(tools)==14 and tools[0]['annotations']['readOnlyHint'] is False
    msg.update(method='tools/call',params={'name':'ygc_pending_test','arguments':{}})
    job=json.loads(c.post(url,json=msg,headers=headers).json()['result']['content'][0]['text'])['jobs'][0]
    msg.update(params={'name':'ygc_submit_test_review','arguments':review(job)})
    assert not c.post(url,json=msg,headers=headers).json()['result'].get('isError')
    admin={'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}
    assert c.get('/api/admin/direct-experiment').status_code==403
    assert c.get('/api/admin/direct-experiment',headers=admin).json()['jobs'][0]['status']=='completed'
    assert c.get('/api/admin/direct-experiment',params={'revision':job['revision']},headers=admin).json()['report_text']
    assert c.post('/api/admin/direct-experiment/connection',headers=admin).json()['token']==data['token']
    assert c.post('/api/admin/direct-experiment/jobs/'+job['revision']+'/delete').status_code==403
    assert c.delete('/api/admin/direct-experiment',headers=admin).status_code==200
    assert c.post(url,json=msg,headers=headers).status_code==401
    assert direct.status()['jobs'][0]['status']=='completed'


def test_notification_cannot_submit_and_body_limit():
    data=prepared();job=claim()[0]
    assert direct.rpc({'jsonrpc':'2.0','method':'tools/call','params':{'name':'ygc_submit_test_review','arguments':review(job)}}) is None
    assert direct.status(job['revision'])['status']=='processing'
    assert client().post('/api/experiments/direct/mcp',content=b' '*100001,
        headers={'Authorization':'Bearer '+data['token'],'Content-Type':'application/json'}).status_code==413


def test_admin_upload_validates_before_saving_and_storage_limit(monkeypatch):
    c=client();headers={'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}
    data={'application_id':'test','serial':'ISSB25003873','challenge':'N3G8PQTS'}
    files={r:('image.jpg',image_bytes(),'image/jpeg') for r in ('closeup','overview','reference')}
    assert c.post('/api/admin/direct-experiment/prepare',data=data,files=files).status_code==403
    response=c.post('/api/admin/direct-experiment/prepare',data=data,files=files,headers=headers)
    assert response.status_code==200
    files['reference']=('bad.jpg',b'not image','image/jpeg')
    assert c.post('/api/admin/direct-experiment/prepare',data=data,files=files,headers=headers).status_code==400
    assert len(direct.status()['jobs'])==1
    monkeypatch.setattr(queue,'MAX_JOBS',1)
    assert prepared('test')['revision']==response.json()['revision']
    with pytest.raises(ValueError):prepared('second')


def test_desktop_stdio_bridge_over_real_loopback():
    import os,socket,subprocess,sys,threading,time
    from pathlib import Path
    import uvicorn
    data=prepared();job=claim()[0]
    messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},
              {'jsonrpc':'2.0','method':'notifications/initialized'},
              {'jsonrpc':'2.0','id':2,'method':'tools/list'},
              {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'ygc_test_image','arguments':key(job)}},
              {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'ygc_submit_test_review','arguments':review(job)}}]
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='critical',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.01)
        assert server.started
        env={**os.environ,'YGC_EXPERIMENT_TOKEN':data['token'],'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
        process=subprocess.run([sys.executable,'-m','ygc.direct_mcp_bridge','--url',f'http://127.0.0.1:{port}/api/experiments/direct/mcp'],
            input='\n'.join(json.dumps(m) for m in messages)+'\n',text=True,capture_output=True,env=env,timeout=10)
        assert process.returncode==0
        replies=[json.loads(line) for line in process.stdout.splitlines()]
        assert len(replies)==4 and replies[2]['result']['content'][1]['type']=='image'
        assert not replies[3]['result'].get('isError')
        assert direct.status(job['revision'])['result']['adjudication']['accepted'] is True
    finally:
        server.should_exit=True;thread.join(timeout=5);sock.close()


def test_snapshot_handles_more_than_three_and_excludes_new_arrivals():
    initial=[prepared(str(i))['revision'] for i in range(5)]
    args={};seen=[]
    while True:
        response=json.loads(direct.call_tool('ygc_pending_test',args)['content'][0]['text'])
        job=response['jobs'][0];seen.append(job['revision'])
        if len(seen)==1:
            late=prepared('late')['revision']
        direct.call_tool('ygc_submit_test_review',review(job))
        args={'remaining_revisions':response['remaining_revisions']}
        if not response['remaining_revisions']:break
    assert seen==initial
    assert direct.status(late)['status']=='pending'
    empty=json.loads(direct.call_tool('ygc_pending_test',args)['content'][0]['text'])
    assert empty['jobs']==[] and empty['remaining_revisions']==[]
    assert claim()[0]['revision']==late


def test_snapshot_skips_cancelled_or_claimed_items():
    a=prepared('a');b=prepared('b');c=prepared('c')
    first=json.loads(direct.call_tool('ygc_pending_test',{})['content'][0]['text'])
    assert first['jobs'][0]['revision']==a['revision']
    direct.manage(b['revision'],'cancel')
    other=claim()[0];assert other['revision']==c['revision']
    next_result=json.loads(direct.call_tool('ygc_pending_test',{'remaining_revisions':first['remaining_revisions']})['content'][0]['text'])
    assert next_result['jobs']==[] and next_result['remaining_revisions']==[]


@pytest.mark.parametrize('route', [
    '/api/admin/authentication-test', '/api/admin/authentication-diagnostic',
    '/api/admin/sheets-experiment/prepare', '/api/admin/sheets-experiment/validate',
])
def test_retired_authentication_routes_are_removed(route):
    assert client().post(route, json={}, headers={'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}).status_code == 404


def test_report_retains_ambiguous_observations_without_rejecting():
    prepared(); job=claim()[0]; raw=review(job)
    raw['identity']['ambiguous_differences']=[
        {'location':'B/C ブリッジ脇','observation':'白いリング。反射か付着物か不明'}]
    direct.call_tool('ygc_submit_test_review',raw)
    result=direct.status(job['revision'])
    assert result['result']['adjudication']['accepted'] is True
    assert '白いリング' in result['report_text']
    assert 'B/C ブリッジ脇' in result['report_text']
