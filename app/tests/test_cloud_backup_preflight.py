"""In-process backup capacity and private-original recovery acceptance checks."""
from contextlib import contextmanager
from collections import defaultdict
from dataclasses import asdict,replace
from datetime import datetime,timezone
import gzip
import hashlib
import json
import sqlite3
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_cloud_avatar import Storage
from ygc import cloud_backup_job as job,cloud_db_restore as restore,cloud_db_snapshot as snapshot
from ygc.cloud_backup_preflight import BackupCapacityError,preflight_legacy_evidence,failure_status
from ygc.cloud_dispute_storage import OriginalUnavailable
from ygc.cloud_storage import MAX_BYTES
from ygc.db.postgres import schema_versions


def archive(rows=None,version=3):
    version,checksum,expected,_=schema_versions('chronicle')[version-1]
    header={'format':snapshot.FORMAT,'target':'chronicle','schema_version':version,
        'schema_checksum':checksum,'tables':expected['tables']}
    records=[header];counts={table:0 for table in header['tables']}
    for table,items in (rows or {}).items():
        for item in items:
            records.append({'table':table,'values':[snapshot.encode_cell(item.get(column),
                snapshot.TYPED_COLUMNS.get(('chronicle',table,column))) for column in header['tables'][table]]})
            counts[table]+=1
    records.append({'sequences':[]})
    raw=b''.join(snapshot.line(record) for record in records)
    data=gzip.compress(raw+snapshot.line({'counts':counts,'sha256':hashlib.sha256(raw).hexdigest()}))
    return data,hashlib.sha256(data).hexdigest()


def fixture_original(store,size=12*1024*1024):
    data=b'%PDF-'+b'x'*(size-5)
    created=store.put('content',data,content_type='application/pdf')
    ref=replace(created,generation=42)
    store.objects[ref]=store.objects.pop(created)
    original=dict(evidence_id=19,object_scope=ref.scope,object_name=ref.name,
        object_generation=ref.generation,byte_size=ref.size,content_type=ref.content_type,
        sha256=hashlib.sha256(data).hexdigest(),created_at='2026-10-07')
    evidence=dict(id=19,dispute_id=1,claim_id=2,author_id=3,explanation='PRIVATE EXPLANATION',
        summary='PRIVATE SUMMARY',filename='document.pdf',content_type='application/pdf',
        content=None,created_at='2026-10-07')
    return ref,{'ownership_dispute_originals':[original],'ownership_dispute_evidence':[evidence]}


def legacy_connection():
    con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
    con.execute('''CREATE TABLE ownership_dispute_evidence(content BLOB, explanation TEXT,
        summary TEXT,published_summary TEXT,published_at TEXT,filename TEXT,content_type TEXT,created_at TEXT)''')
    return con


def test_metadata_first_legacy_limit_never_fetches_or_logs_private_bytes():
    with legacy_connection() as con:
        con.execute("INSERT INTO ownership_dispute_evidence VALUES(zeroblob(?),'PRIVATE TEXT','PRIVATE SUMMARY',NULL,NULL,'PRIVATE FILE','application/pdf','now')",(12*1024*1024,))
        queries=[];con.set_trace_callback(queries.append)
        with pytest.raises(BackupCapacityError) as caught:preflight_legacy_evidence(con)
        con.set_trace_callback(None)
    assert caught.value.code=='legacy_evidence_line_limit'
    assert caught.value.stage=='legacy_evidence_preflight'
    assert caught.value.aggregates['legacy_rows']==1 and caught.value.aggregates['legacy_bytes']==12*1024*1024
    assert len(queries)==1 and 'length(content)' in queries[0] and 'SELECT content' not in queries[0]
    report=json.dumps(failure_status(caught.value,'snapshot'))+str(caught.value)
    assert all(secret not in report for secret in ('PRIVATE TEXT','PRIVATE FILE','PRIVATE SUMMARY','media/'))


def test_legacy_total_limit_and_unicode_metadata_are_conservative():
    with legacy_connection() as con:
        con.execute("INSERT INTO ownership_dispute_evidence VALUES(zeroblob(10),'😀','summary',NULL,NULL,'document.pdf','application/pdf','now')")
        report=preflight_legacy_evidence(con)
        assert report['legacy_rows']==1 and report['legacy_bytes']==10
        assert report['largest_legacy_line_bound']>=16+12+512
    con=Mock();con.execute.return_value.fetchone.return_value=dict(legacy_rows=30,
        legacy_bytes=30*1024*1024,largest_legacy_bytes=1024*1024,
        largest_legacy_line_bound=2*1024*1024,legacy_raw_bound=40*1024*1024)
    with pytest.raises(BackupCapacityError,match='restore staging') as caught:preflight_legacy_evidence(con)
    assert caught.value.code=='legacy_evidence_restore_limit'


def test_twelve_mib_original_stays_external_and_fixed_generation_round_trips():
    store=Storage();ref,rows=fixture_original(store)
    data,sha=archive(rows)
    assert len(data)<20000 and sum(len(value) for value in store.objects.values())==12*1024*1024
    header,loaded,sequences=restore.load(data,'chronicle',sha)
    assert loaded['ownership_dispute_originals']==rows['ownership_dispute_originals']
    assert loaded['ownership_dispute_evidence'][0]['content'] is None
    restore.verify_restored_dispute_originals(store,loaded)
    assert header['schema_version']==3 and not store.deleted and ref in store.objects


@pytest.mark.parametrize('failure',['generation','hash','size','scope','mime','missing_object',
    'missing_reference','missing_evidence','dual_content','duplicate_reference','duplicate_object'])
def test_invalid_originals_fail_before_any_destructive_restore(monkeypatch,failure):
    store=Storage();ref,rows=fixture_original(store,128)
    original=rows['ownership_dispute_originals'][0];evidence=rows['ownership_dispute_evidence'][0]
    if failure=='generation':original['object_generation']+=1
    if failure=='hash':original['sha256']='0'*64
    if failure=='size':original['byte_size']+=1
    if failure=='scope':original['object_scope']='accounts'
    if failure=='mime':original['content_type']='image/jpeg'
    if failure=='missing_object':del store.objects[ref]
    if failure=='missing_reference':rows['ownership_dispute_originals']=[]
    if failure=='missing_evidence':rows['ownership_dispute_evidence']=[]
    if failure=='dual_content':evidence['content']=b'legacy bytes'
    if failure=='duplicate_reference':rows['ownership_dispute_originals'].append(dict(original))
    if failure=='duplicate_object':rows['ownership_dispute_originals'].append(dict(original,evidence_id=20))
    data,sha=archive(rows);header,loaded,sequences=restore.load(data,'chronicle',sha)
    con=Mock();con.execute.return_value.fetchone.return_value={'version':3,'checksum':header['schema_checksum']}
    monkeypatch.setattr(restore,'validate_schema',lambda con,expected:None)
    destructive=Mock();monkeypatch.setattr(restore,'order',destructive)
    with pytest.raises((ValueError,OriginalUnavailable)):restore.replace_content(con,header,loaded,sequences,[],storage=store)
    destructive.assert_not_called()
    assert len(con.execute.call_args_list)==1 and not store.deleted


@pytest.mark.parametrize('version',[1,2])
def test_known_old_archives_restore_only_exact_additive_schemas(version):
    data,sha=archive(version=version);header,rows,_=restore.load(data,'chronicle',sha)
    current_version,checksum,expected,_=schema_versions('chronicle')[-1]
    dest={'version':current_version,'checksum':checksum}
    assert restore.content_restore_schema(header,dest)==expected
    assert 'ownership_dispute_originals' not in rows
    restore.verify_restored_dispute_originals(None,rows)
    for changed in (dict(header,schema_checksum='0'*64),dict(header,schema_version=99),
            dict(header,tables={**header['tables'],'extra':['id']})):
        with pytest.raises(ValueError):restore.content_restore_schema(changed,dest)
    with pytest.raises(ValueError):restore.content_restore_schema(header,dict(dest,checksum='0'*64))


def test_no_future_or_reverse_schema_bridge():
    data,sha=archive();header,rows,_=restore.load(data,'chronicle',sha)
    version,checksum,_,_=schema_versions('chronicle')[1]
    with pytest.raises(ValueError):restore.content_restore_schema(header,{'version':version,'checksum':checksum})


@pytest.mark.parametrize('version',[1,2])
def test_old_restore_explicitly_clears_new_reference_table_without_changing_header(monkeypatch,version):
    data,sha=archive(version=version);header,rows,sequences=restore.load(data,'chronicle',sha)
    version,checksum,expected,_=schema_versions('chronicle')[-1]
    con=Mock();con.execute.return_value.fetchone.return_value={'version':version,'checksum':checksum}
    monkeypatch.setattr(restore,'validate_schema',lambda *_:None)
    monkeypatch.setattr(restore,'order',lambda con,tables:(sorted(tables),defaultdict(list)))
    monkeypatch.setattr(restore,'sequence_state',lambda con:{})
    advance=Mock();monkeypatch.setattr(restore,'advance_sequences',advance)
    inserted={};monkeypatch.setattr(restore,'insert',lambda con,table,columns,values:inserted.update({table:values}))
    restore.replace_content(con,header,rows,sequences,[])
    assert inserted['ownership_dispute_originals']==[]
    assert inserted['account_projection_receipts']==[]
    assert set(inserted)==set(expected['tables'])
    assert 'ownership_dispute_originals' not in header['tables'] and 'ownership_dispute_originals' not in rows
    advance.assert_called_once()
    calls=[call.args[0].as_string() for call in con.execute.call_args_list if hasattr(call.args[0],'as_string')]
    assert 'DELETE FROM "ownership_dispute_originals"' in calls


def test_current_archive_never_gets_an_implicitly_empty_reference_table(monkeypatch):
    data,sha=archive();header,rows,sequences=restore.load(data,'chronicle',sha)
    del rows['ownership_dispute_originals']
    con=Mock();con.execute.return_value.fetchone.return_value={'version':3,'checksum':header['schema_checksum']}
    monkeypatch.setattr(restore,'validate_schema',lambda *_:None)
    with pytest.raises(ValueError,match='table data'):restore.replace_content(con,header,rows,sequences,[])
    assert len(con.execute.call_args_list)==1


def test_old_archive_verification_limit_is_not_restore_staging_limit(monkeypatch):
    data,sha=archive({'ownership_dispute_evidence':[dict(id=1,content=b'x'*5000,content_type='application/pdf')]},version=2)
    monkeypatch.setattr(restore,'MAX_RESTORE_RAW',1000)
    assert snapshot.verify_snapshot(data,'chronicle',sha)['schema_version']==2
    assert job.verify_chronicle_archive(None,data,sha,restore_ready=False)['schema_version']==2
    with pytest.raises(BackupCapacityError) as caught:restore.load(data,'chronicle',sha)
    assert caught.value.code=='restore_staging_limit'


def test_save_checks_original_before_upload_and_again_after_readback(monkeypatch):
    store=Storage();ref,rows=fixture_original(store,128);data,sha=archive(rows)
    meta=dict(target='chronicle',schema_version=3,created_at='now',tables=1,rows=2,sha256=sha)
    monkeypatch.setattr(job,'snapshot',lambda *_:(data,meta))
    con=Mock();con.execute.return_value.fetchone.return_value={'locked':True}
    @contextmanager
    def connect(*_):yield con
    monkeypatch.setattr(job,'connect',connect)
    seen=[];read=store.get
    def get(reference):seen.append(reference);return read(reference)
    store.get=get
    assert job.save(None,store,'chronicle','fixture')['saved']
    assert seen.count(ref)==2 and not store.deleted
    del store.objects[ref];before=set(store.objects);con.commit.reset_mock()
    with pytest.raises(OriginalUnavailable):job.save(None,store,'chronicle','fixture')
    assert set(store.objects)==before and not store.deleted
    con.commit.assert_not_called()


def test_save_failure_compensates_archive_only_never_evidence(monkeypatch):
    store=Storage();ref,rows=fixture_original(store,128);data,sha=archive(rows)
    monkeypatch.setattr(job,'snapshot',lambda *_:(data,dict(target='chronicle',schema_version=3,
        created_at='now',tables=1,rows=2,sha256=sha)))
    con=Mock();con.execute.return_value.fetchone.return_value={'locked':True}
    @contextmanager
    def connect(*_):yield con
    monkeypatch.setattr(job,'connect',connect)
    read=store.get;count=0
    def get(reference):
        nonlocal count
        if reference==ref:
            count+=1
            if count==2:raise RuntimeError('private provider failure')
        return read(reference)
    store.get=get
    with pytest.raises(OriginalUnavailable):job.save(None,store,'chronicle','fixture')
    assert list(store.objects)==[ref] and len(store.deleted)==1
    assert store.deleted[0].content_type=='application/gzip'


def test_preflight_is_read_only_and_names_its_narrow_guarantees(monkeypatch):
    store=Storage();ref,rows=fixture_original(store,128);data,sha=archive(rows)
    meta=dict(schema_version=3,tables=1,rows=2,raw_bytes=1000,compressed_bytes=len(data),
        legacy_rows=0,legacy_bytes=0,largest_legacy_bytes=0,largest_legacy_line_bound=0,legacy_raw_bound=0,sha256=sha)
    monkeypatch.setattr(job,'snapshot',lambda *_:(data,meta));before=dict(store.objects)
    result=job.preflight(None,store,'chronicle')
    assert result['data_changed'] is False and result['snapshot_within_restore_capacity']
    assert result['dispute_originals_verified'] and 'restore_ready' not in result
    assert store.objects==before and not store.deleted
    assert ref.name not in json.dumps(result) and 'PRIVATE' not in json.dumps(result)


def test_existing_size_constants_are_unchanged():
    assert snapshot.MAX_LINE==8*1024*1024 and snapshot.MAX_RAW==128*1024*1024
    assert MAX_BYTES==25*1024*1024 and restore.MAX_RESTORE_RAW==32*1024*1024


def test_snapshot_checks_metadata_before_fetching_rows_and_enforces_chronicle_capacity_only(monkeypatch):
    legacy=dict(legacy_rows=0,legacy_bytes=0,largest_legacy_bytes=0,
        largest_legacy_line_bound=0,legacy_raw_bound=0)
    con=Mock();con.execute.return_value.fetchone.return_value={'version':1,'checksum':'fixture'}
    con.execute.return_value.__iter__=lambda _:iter([])
    cursor=Mock();con.cursor.return_value.__enter__=lambda _:cursor
    con.cursor.return_value.__exit__=lambda *_:None
    @contextmanager
    def connection(*_):yield con
    monkeypatch.setattr(snapshot,'connect',connection)
    monkeypatch.setattr(snapshot,'recorded_schema',lambda *_:{'tables':{'fixture':['id','payload']}})
    monkeypatch.setattr(snapshot,'validate_schema',lambda *_:None)
    preflight=Mock(side_effect=BackupCapacityError('legacy_evidence_line_limit','legacy_evidence_preflight'))
    monkeypatch.setattr(snapshot,'preflight_legacy_evidence',preflight)
    with pytest.raises(BackupCapacityError):snapshot.snapshot(None,'chronicle')
    con.cursor.assert_not_called()
    preflight.side_effect=None;preflight.return_value=legacy
    monkeypatch.setattr(snapshot,'MAX_RESTORE_RAW',12000)
    rows=[{'id':index,'payload':'x'*4000} for index in range(5)]
    cursor.fetchmany.side_effect=[rows,[]]
    with pytest.raises(BackupCapacityError) as caught:snapshot.snapshot(None,'chronicle')
    assert caught.value.code=='chronicle_restore_capacity'
    cursor.fetchmany.side_effect=[rows,[]]
    data,meta=snapshot.snapshot(None,'accounts')
    assert meta['raw_bytes']>12000 and meta['compressed_bytes']==len(data)


def test_cli_preflight_failure_only_emits_safe_aggregate_code(monkeypatch,capsys):
    monkeypatch.setenv('YGC_GCP_PROJECT_ID','test-project')
    monkeypatch.setenv('CLOUD_RUN_JOB','test-backup')
    monkeypatch.setenv('YGC_DATABASE_BACKEND','postgres')
    monkeypatch.delenv('K_SERVICE',raising=False)
    store=Mock();monkeypatch.setattr(job,'CloudStorage',lambda *_:store)
    monkeypatch.setattr(job.StorageSettings,'from_environment',lambda *_:None)
    monkeypatch.setattr(job.PostgresSettings,'from_environment',lambda:SimpleNamespace(host='/cloudsql/test-project:fixture'))
    def fail(*_):raise BackupCapacityError('legacy_evidence_line_limit','legacy_evidence_preflight',{'legacy_rows':1,'legacy_bytes':12*1024*1024})
    monkeypatch.setattr(job,'preflight',fail)
    assert job.main(['--confirm-project','test-project','--target','chronicle','--preflight-only'])==1
    result=json.loads(capsys.readouterr().err)
    assert result==dict(status='failed',stage='legacy_evidence_preflight',code='legacy_evidence_line_limit',legacy_rows=1,legacy_bytes=12*1024*1024)
    store.put.assert_not_called();store.delete.assert_not_called();store.close.assert_called_once()


def test_retention_removes_archives_without_deleting_their_originals(monkeypatch):
    from ygc import cloud_backup_policy as policy
    store=Storage();original,evidence=fixture_original(store,128);data,sha=archive(evidence)
    rows=[];archives=[]
    for index in range(2):
        ref=store.put('content',data,content_type='application/gzip');archives.append(ref)
        rows.insert(0,{'id':index+1,'reason':json.dumps({'kind':job.KIND,'backup_id':str(index),
            'target':'chronicle','object':asdict(ref),'sha256':sha})})
    con=Mock()
    con.execute.side_effect=lambda sql,params:SimpleNamespace(fetchone=lambda:{'generations':1},
        fetchall=lambda:[] if isinstance(params[0],str) and 'maintenance_request' in params[0] else rows)
    @contextmanager
    def connection(*_):yield con
    monkeypatch.setattr(policy,'connect',connection)
    assert policy.prune(None,store,'chronicle')==1
    assert store.deleted==[archives[0]] and original in store.objects and archives[1] in store.objects


def test_maintenance_rejects_missing_original_before_safety_copy_or_database_replacement(monkeypatch):
    from ygc import cloud_maintenance_job as maintenance
    store=Storage();original,rows=fixture_original(store,128);data,sha=archive(rows)
    selected=store.put('content',data,content_type='application/gzip');del store.objects[original]
    token=str(uuid.uuid4())
    record=dict(state='starting',target='chronicle',action='restore',backup_id='selected',
        created_at=datetime.now(timezone.utc).isoformat(),actor='admin')
    event={'id':1,'reason':json.dumps(record)}
    backup=dict(target='chronicle',object=asdict(selected),sha256=sha)
    con=Mock()
    def execute(query,*args):
        if 'SELECT reason FROM events' in query:return SimpleNamespace(fetchone=lambda:{'reason':json.dumps(backup)})
        if 'pg_try_advisory_lock' in query:return SimpleNamespace(fetchone=lambda:{'locked':True})
        return Mock()
    con.execute.side_effect=execute
    @contextmanager
    def connection(settings,target):
        assert target=='operations', 'Archive originals must be checked before opening any replacement connection.'
        yield con
    monkeypatch.setattr(maintenance,'connect',connection)
    monkeypatch.setattr(maintenance,'_find',lambda *_:event)
    safety=Mock();monkeypatch.setattr(maintenance,'save',safety)
    with pytest.raises(OriginalUnavailable):maintenance.perform(None,store,token,'fixture')
    safety.assert_not_called()
    assert not store.deleted and list(store.objects)==[selected]
    assert not any('DELETE' in call.args[0] for call in con.execute.call_args_list)
