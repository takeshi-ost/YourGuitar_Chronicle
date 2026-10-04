"""IAM-only independent DB save/verification Job; no restore or automatic schedule."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
import os
import sys
import uuid
from ygc.cloud_db_snapshot import snapshot,verify_snapshot
from ygc.cloud_storage import CloudStorage,StorageSettings,ObjectReference
from ygc.db.postgres import PostgresSettings,TARGETS,connect

KIND='db_backup_v1'


def save(settings,storage,target,execution,progress=lambda stage:None,request_id=None):
    if target not in TARGETS:raise ValueError('Unknown target.')
    # Lock one target, not all four DBs. Immutable image objects are retained separately.
    candidate=None;committing=False
    progress('catalog_lock')
    with connect(settings,'operations') as catalog:
        if not catalog.execute('SELECT pg_try_advisory_xact_lock(%s) AS locked',(79432100+TARGETS.index(target),)).fetchone()['locked']:
            raise RuntimeError('Backup target busy.')
        try:
            progress('snapshot')
            data,meta=snapshot(settings,target)
            progress('archive_verification')
            verify_snapshot(data,target,meta['sha256'])
            progress('upload')
            candidate=storage.put('content' if target=='chronicle' else 'accounts',data,content_type='application/gzip')
            progress('read_back')
            if hashlib.sha256(storage.get(candidate)).hexdigest()!=meta['sha256']:raise ValueError('Read-back mismatch.')
            record={'kind':KIND,'backup_id':str(uuid.uuid4()),**meta,'object':asdict(candidate),'execution':execution}
            if request_id is not None:record['request_id']=request_id
            progress('catalog_commit')
            catalog.execute('INSERT INTO events(occurred_at,mode,reason) SELECT %s,mode,%s FROM settings WHERE id=1',
                (datetime.now(timezone.utc).isoformat(),json.dumps(record,separators=(',',':'))))
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
    result=verify_snapshot(storage.get(ref),target,record['sha256'])
    return {'status':'ok','target':target,'verified':True,'tables':result['tables']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-project',required=True);parser.add_argument('--target',required=True,choices=TARGETS)
    parser.add_argument('--verify-only',action='store_true');args=parser.parse_args(argv)
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
        if args.verify_only:progress('read_back_verification')
        result=verify_latest(settings,storage,args.target) if args.verify_only else save(settings,storage,args.target,execution,progress,token)
        print(json.dumps(result));return 0
    except Exception:
        print(json.dumps({'status':'failed','stage':stage}),file=sys.stderr);return 1
    finally:
        if storage is not None:storage.close()


if __name__=='__main__':raise SystemExit(main())
