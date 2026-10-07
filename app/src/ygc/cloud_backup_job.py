"""IAM-only independent DB save/verification Job; no restore or automatic schedule."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
import os
import sys
import uuid
import time
from ygc.cloud_db_snapshot import snapshot,verify_snapshot
from ygc.cloud_storage import CloudStorage,StorageSettings,ObjectReference
from ygc.db.postgres import PostgresSettings,TARGETS,connect
from ygc.cloud_backup_preflight import failure_status

KIND='db_backup_v1'


def verify_chronicle_archive(storage,data,sha,*,restore_ready=True):
    """Bound staging and verify each private original, without deleting anything."""
    from ygc.cloud_db_restore import load,verify_restored_dispute_originals,verify_dispute_originals
    if not restore_ready:
        # Old archives retain the 128 MiB verification contract. Collect only
        # attachment metadata, discarding legacy BYTEA before the next row.
        import gzip
        from io import BytesIO
        from ygc.cloud_db_snapshot import decode_cell
        verify_snapshot(data,'chronicle',sha)
        evidence=[];originals=[]
        with gzip.GzipFile(fileobj=BytesIO(data)) as source:
            header=json.loads(source.readline())
            for raw in source:
                row=json.loads(raw);table=row.get('table')
                if table not in ('ownership_dispute_evidence','ownership_dispute_originals'):continue
                item=dict(zip(header['tables'][table],row['values']))
                if table=='ownership_dispute_originals':originals.append(item)
                else:
                    content=decode_cell(item['content'],'bytea')
                    evidence.append({'id':item['id'],'content_type':item['content_type'],
                        'content_size':None if content is None else len(content)})
        verify_dispute_originals(storage,originals,evidence)
        return header
    header,rows,sequences=load(data,'chronicle',sha)
    verify_restored_dispute_originals(storage,rows)
    return header


def preflight(settings,storage,target,progress=lambda stage:None):
    if target!='chronicle':raise ValueError('Chronicle preflight required.')
    progress('legacy_evidence_preflight')
    data,meta=snapshot(settings,target)
    progress('evidence_reference_verification')
    verify_chronicle_archive(storage,data,meta['sha256'])
    return {'status':'ok','target':target,'data_changed':False,
        'snapshot_within_restore_capacity':True,'dispute_originals_verified':True,
        **{key:meta[key] for key in ('schema_version','tables','rows','raw_bytes','compressed_bytes',
            'legacy_rows','legacy_bytes','largest_legacy_bytes','largest_legacy_line_bound','legacy_raw_bound')}}


def save(settings,storage,target,execution,progress=lambda stage:None,request_id=None,scheduled=False,source=None):
    if target not in TARGETS or source not in (None,'manual','scheduled','crawl','pre_restore'):raise ValueError('Unknown target or source.')
    # Lock one target, not all four DBs. Immutable image objects are retained separately.
    candidate=None;committing=False
    progress('catalog_lock')
    with connect(settings,'operations') as catalog:
        if not catalog.execute('SELECT pg_try_advisory_xact_lock(%s) AS locked',(79432100+TARGETS.index(target),)).fetchone()['locked']:
            raise RuntimeError('Backup target busy.')
        if scheduled:
            schedule=catalog.execute('SELECT * FROM backup_schedules WHERE target=%s FOR UPDATE',(target,)).fetchone()
            if not schedule['enabled'] or schedule['next_run']>time.time():return {'status':'ok','target':target,'skipped':True}
        try:
            progress('snapshot')
            data,meta=snapshot(settings,target)
            progress('archive_verification')
            verify_snapshot(data,target,meta['sha256'])
            if target=='chronicle':
                progress('evidence_reference_verification')
                verify_chronicle_archive(storage,data,meta['sha256'])
            progress('upload')
            candidate=storage.put('content' if target=='chronicle' else 'accounts',data,content_type='application/gzip')
            progress('read_back')
            read_back=storage.get(candidate)
            if hashlib.sha256(read_back).hexdigest()!=meta['sha256']:raise ValueError('Read-back mismatch.')
            if target=='chronicle':verify_chronicle_archive(storage,read_back,meta['sha256'])
            record={'kind':KIND,'backup_id':str(uuid.uuid4()),**meta,'object':asdict(candidate),'execution':execution}
            if request_id is not None:record['request_id']=request_id
            record['source']=source or ('scheduled' if scheduled else 'manual')
            progress('catalog_commit')
            catalog.execute('INSERT INTO events(occurred_at,mode,reason) SELECT %s,mode,%s FROM settings WHERE id=1',
                (datetime.now(timezone.utc).isoformat(),json.dumps(record,separators=(',',':'))))
            catalog.execute("UPDATE backup_schedules SET last_at=%s,last_status='ok',last_error=NULL WHERE target=%s",(meta['created_at'],target))
            if scheduled:
                catalog.execute('UPDATE backup_schedules SET next_run=%s WHERE target=%s',((int(time.time()//3600)+schedule['interval_hours'])*3600,target))
            committing=True
            catalog.commit()
            return {'status':'ok','target':target,'saved':True,'read_back_verified':True,'tables':meta['tables']}
        except Exception:
            if candidate is not None and not committing:
                try:storage.delete(candidate)
                except Exception:pass
            raise


def verify_latest(settings,storage,target):
    if target not in TARGETS:raise ValueError('Unknown target.')
    with connect(settings,'operations') as catalog:
        catalog.execute('SET TRANSACTION READ ONLY')
        row=catalog.execute("SELECT reason FROM events WHERE CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'target'=%s ORDER BY id DESC LIMIT 1",('{\"kind\":\"'+KIND+'\",%',target)).fetchone()
        if row is None:raise ValueError('No saved snapshot.')
        record=json.loads(row['reason'])
    ref=ObjectReference(**record['object'])
    if ref.scope!=('content' if target=='chronicle' else 'accounts') or ref.content_type!='application/gzip':raise ValueError('Wrong backup scope.')
    data=storage.get(ref)
    result=verify_snapshot(data,target,record['sha256'])
    if target=='chronicle':verify_chronicle_archive(storage,data,record['sha256'],restore_ready=False)
    return {'status':'ok','target':target,'verified':True,'tables':result['tables']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-project',required=True);parser.add_argument('--target',choices=TARGETS)
    inspection=parser.add_mutually_exclusive_group()
    inspection.add_argument('--verify-only',action='store_true')
    inspection.add_argument('--preflight-only',action='store_true',help='Read-only Chronicle legacy capacity and original-reference check; no archive upload')
    parser.add_argument('--scheduled',action='store_true');args=parser.parse_args(argv)
    if (args.target is None)!=args.scheduled or (args.scheduled and args.verify_only):parser.error('Select one target or the scheduled worker.')
    if args.preflight_only and (args.scheduled or args.target!='chronicle'):parser.error('Preflight requires --target=chronicle.')
    storage=None;stage='configuration'
    def progress(value):
        nonlocal stage
        stage=value
        print(json.dumps({'stage':value}),flush=True)
    try:
        project=os.environ.get('YGC_GCP_PROJECT_ID','')
        if args.confirm_project!=project or not os.environ.get('CLOUD_RUN_JOB') or os.environ.get('K_SERVICE') or os.environ.get('CLOUD_RUN_TASK_COUNT','1')!='1':raise ValueError('Use a confirmed single-task Job.')
        if os.environ.get('YGC_DATABASE_BACKEND')!='postgres':raise ValueError('Explicit PostgreSQL required.')
        storage=CloudStorage(StorageSettings.from_environment(project));settings=PostgresSettings.from_environment()
        if not settings.host.startswith('/cloudsql/'+project+':'):raise ValueError('Cloud SQL project mismatch.')
        execution=os.environ.get('CLOUD_RUN_EXECUTION','')
        token=os.environ.get('YGC_BACKUP_REQUEST_ID')
        if token is not None and str(uuid.UUID(token))!=token:raise ValueError('Invalid request UUID.')
        if args.preflight_only:
            print(json.dumps(preflight(settings,storage,args.target,progress)));return 0
        if args.scheduled:
            from ygc.cloud_backup_policy import prune
            failed=False;saved=0
            for target in TARGETS:
                try:
                    result=save(settings,storage,target,execution,progress,scheduled=True)
                    if result.get('saved'):saved+=1;prune(settings,storage,target)
                except Exception as exc:
                    failed=True
                    with connect(settings,'operations') as con:
                        safe=failure_status(exc,stage)
                        con.execute("UPDATE backup_schedules SET last_status='failed',last_error=%s WHERE target=%s",(safe.get('code','Backup worker failed.'),target))
                    print(json.dumps({'target':target,**safe}),file=sys.stderr)
            print(json.dumps({'status':'failed' if failed else 'ok','saved_targets':saved}));return int(failed)
        if args.verify_only:progress('read_back_verification')
        result=verify_latest(settings,storage,args.target) if args.verify_only else save(settings,storage,args.target,execution,progress,token)
        if not args.verify_only:
            from ygc.cloud_backup_policy import prune
            try:result['pruned']=prune(settings,storage,args.target)
            except Exception:result['retention_pending']=True
        print(json.dumps(result));return 0
    except Exception as exc:
        print(json.dumps(failure_status(exc,stage)),file=sys.stderr);return 1
    finally:
        if storage is not None:storage.close()


if __name__=='__main__':raise SystemExit(main())
