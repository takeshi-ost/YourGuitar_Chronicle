from contextlib import contextmanager
from dataclasses import asdict
import gzip
import hashlib
import json
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_db_snapshot import verify_snapshot,line,FORMAT
from ygc.db.postgres import schema_versions
from ygc.cloud_backup_routes import backup_router,catalog
from ygc.identity_platform import VerifiedIdentity
from ygc import cloud_backup_job as job


def archive(target='accounts',change=None):
    version,checksum,expected,_=schema_versions(target)[-1]
    header={'format':FORMAT,'target':target,'schema_version':version,'schema_checksum':checksum,'tables':expected['tables']}
    records=[header,{'sequences':[]}]
    if change:change(records)
    raw=b''.join(map(line,records));counts={t:0 for t in expected['tables']}
    data=gzip.compress(raw+line({'counts':counts,'sha256':hashlib.sha256(raw).hexdigest()}))
    return data,hashlib.sha256(data).hexdigest()


def test_versioned_archive_validation_and_integrity():
    data,sha=archive();result=verify_snapshot(data,'accounts',sha)
    assert result['target']=='accounts' and result['rows']==0 and result['tables']==8
    with pytest.raises(ValueError):verify_snapshot(data,'chronicle',sha)
    with pytest.raises(ValueError):verify_snapshot(data+b'corrupt','accounts',sha)
    with pytest.raises(ValueError):verify_snapshot(data,'accounts','0'*64)


@pytest.mark.parametrize('change',[lambda r:r[0].update(format='unknown'),lambda r:r[0].update(schema_version=99),
    lambda r:r[0]['tables'].update(extra=['id']),lambda r:r.append({'table':'unknown','values':[]}),
    lambda r:r[1]['sequences'].append({'name':'../escape','last_value':1,'is_called':True})])
def test_unknown_format_schema_or_records_rejected(change):
    data,sha=archive(change=change)
    with pytest.raises(ValueError):verify_snapshot(data,'accounts',sha)


def test_decompression_limits_before_parsing(monkeypatch):
    import ygc.cloud_db_snapshot as module
    data,sha=archive();monkeypatch.setattr(module,'MAX_RAW',10)
    with pytest.raises(ValueError):verify_snapshot(data,'accounts',sha)


@pytest.fixture
def api():
    verifier=Mock();verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True)
    verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical','role':'admin'}
    ops=Mock();con=Mock();con.execute.return_value.fetchall.return_value=[]
    @contextmanager
    def access(kind,actor):
        if ops.fail:raise ops.fail
        yield con,{},{}
    ops.fail=None;ops.access.side_effect=access
    app=FastAPI();app.include_router(backup_router(verifier,ops))
    with TestClient(app) as client:yield client,verifier,ops,con


AUTH={'Authorization':'Bearer token'}


def test_catalog_admin_rechecks_and_whitelists(api):
    client,verifier,ops,con=api
    con.execute.return_value.fetchall.return_value=[{'reason':json.dumps({'backup_id':'id','target':'accounts','created_at':'now','schema_version':2,'tables':8,'rows':3,'object':{'private':'reference'},'sha256':'secret','execution':'private'})}]
    response=client.get('/api/admin/backups?target=accounts',headers=AUTH)
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    assert set(response.json()['items'][0])=={'backup_id','target','created_at','schema_version','tables','rows'}
    assert response.json()['restore_available'] is False and 'private' not in response.text
    ops.access.assert_called_once_with('admin_read','canonical')


@pytest.mark.parametrize('failure,status',[('missing',401),('token',401),('email',403),('member',403),('disabled',403),('recheck',403)])
def test_no_catalog_for_unauthorized(api,failure,status):
    client,verifier,ops,con=api;headers=AUTH
    if failure=='missing':headers={}
    if failure=='token':verifier.verify.side_effect=PermissionError()
    if failure=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if failure=='member':verifier.accounts.resolve_identity.return_value['role']='member'
    if failure=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError()
    if failure=='recheck':ops.fail=PermissionError()
    assert client.get('/api/admin/backups?target=accounts',headers=headers).status_code==status
    con.execute.assert_not_called()


@pytest.mark.parametrize('query',['','target=unknown','target=accounts&target=chronicle','target=accounts&user_id=1'])
def test_catalog_queries_strict(api,query):
    client,verifier,ops,con=api
    assert client.get('/api/admin/backups?'+query,headers=AUTH).status_code==400
    con.execute.assert_not_called()


def test_save_and_progress_admin_only_and_strict_payloads(api):
    import uuid
    client,verifier,ops,con=api
    control=Mock();control.start.return_value={'state':'running'};control.status.return_value={'state':'idle'}
    app=FastAPI();app.include_router(backup_router(verifier,ops,control))
    token=str(uuid.uuid4())
    with TestClient(app) as client:
        payload={'target':'accounts','request_id':token}
        assert client.post('/api/admin/backups/save',json=payload).status_code==401
        verifier.accounts.resolve_identity.return_value['role']='member'
        assert client.post('/api/admin/backups/save',json=payload,headers=AUTH).status_code==403
        control.start.assert_not_called()
        verifier.accounts.resolve_identity.return_value['role']='admin'
        for bad in [{},dict(payload,user_id='fake'),{'target':'accounts'},[],{'target':'accounts','request_id':token,'job':'foreign'}]:
            assert client.post('/api/admin/backups/save',json=bad,headers=AUTH).status_code==400
        assert client.post('/api/admin/backups/save?target=accounts',json=payload,headers=AUTH).status_code==400
        assert client.get('/api/admin/backups/save-status?target=accounts&target=chronicle',headers=AUTH).status_code==400
        assert client.post('/api/admin/backups/save',json=payload,headers=AUTH).json()=={'state':'running'}
        control.start.assert_called_once_with('canonical','accounts',token)
        assert client.get('/api/admin/backups/save-status?target=accounts',headers=AUTH).json()=={'state':'idle'}
        control.status.assert_called_once_with('canonical','accounts')


def test_job_requires_confirmed_single_task_and_never_exposes_error(monkeypatch,capsys):
    monkeypatch.setenv('YGC_GCP_PROJECT_ID','test-project');monkeypatch.setenv('K_SERVICE','web')
    constructor=Mock();monkeypatch.setattr(job,'CloudStorage',constructor)
    assert job.main(['--confirm-project','test-project','--target','accounts'])==1
    constructor.assert_not_called();assert json.loads(capsys.readouterr().err)=={'status':'failed','stage':'configuration'}


@pytest.mark.parametrize('failure,retained',[('readback',False),('commit',True)])
def test_save_compensation_and_uncertain_commit(monkeypatch,failure,retained):
    from test_cloud_avatar import Storage
    store=Storage();data,sha=archive()
    monkeypatch.setattr(job,'snapshot',lambda settings,target:(data,{'target':target,'schema_version':2,'created_at':'now','tables':8,'rows':0,'sha256':sha}))
    con=Mock();con.execute.return_value.fetchone.return_value={'locked':True}
    @contextmanager
    def connection(settings,target):yield con
    monkeypatch.setattr(job,'connect',connection)
    if failure=='readback':store.get=lambda ref:b'corrupt'
    else:con.commit.side_effect=RuntimeError('commit outcome unknown')
    with pytest.raises((ValueError,RuntimeError)):job.save(None,store,'accounts','fixture')
    assert bool(store.objects)==retained
    assert bool(store.deleted)!=retained


def test_timestamp_and_binary_cells_round_trip_without_string_coercion():
    from datetime import datetime,timezone,timedelta
    from ygc.cloud_db_snapshot import encode_cell,decode_cell
    value=datetime(2026,10,5,1,2,3,456789,tzinfo=timezone(timedelta(hours=9)))
    assert decode_cell(encode_cell(value,'timestamptz'),'timestamptz')==value
    binary=bytes(range(256))+b'\x00\xffprivate binary'
    assert decode_cell(encode_cell(memoryview(binary),'bytea'),'bytea')==binary
    for cell,kind in [({'type':'bytea','value':'!bad'},'bytea'),({'type':'timestamptz','value':'2026-01-01'},'timestamptz'),({'type':'bytea','value':'YQ=='},'timestamptz')]:
        with pytest.raises(ValueError):decode_cell(cell,kind)
    with pytest.raises(ValueError):encode_cell(value)
