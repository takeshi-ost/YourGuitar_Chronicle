"""IAM-only worker for persisted, canonical-Admin-authorized maintenance requests."""
import argparse
from datetime import datetime,timezone
import json
import os
import sys
import uuid
from ygc.db.postgres import connect,PostgresSettings,TARGETS
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.cloud_storage import CloudStorage,StorageSettings,ObjectReference
from ygc.cloud_backup_job import save,KIND
from ygc.cloud_db_restore import load,replace_content,restore_accounts

REQUEST_KIND='db_maintenance_request_v1'


def _find(con,token):
    return con.execute("SELECT id,reason FROM events WHERE CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'request_id'=%s ORDER BY id DESC LIMIT 1",('{"kind":"'+REQUEST_KIND+'",%',token)).fetchone()


def update(con,event,record,state):
    record['state']=state
    con.execute('UPDATE events SET reason=%s WHERE id=%s',(json.dumps(record,separators=(',',':')),event))
    con.commit()


def perform(settings,storage,token,execution,progress=lambda stage:None):
    from psycopg import sql
    if str(uuid.UUID(token))!=token:raise ValueError('Invalid request UUID.')
    with connect(settings,'operations') as catalog:
        catalog.execute("SET LOCAL lock_timeout='5s'")
        event=_find(catalog,token)
        if not event:raise PermissionError('Persisted administrator request required.')
        record=json.loads(event['reason'])
        if record['state'] not in ('starting','running','unknown'):return {'status':'ok','already_completed':True}
        target=record['target'];action=record['action']
        if target not in TARGETS or action not in ('restore','reset'):raise ValueError('Invalid maintenance request.')
        if (datetime.now(timezone.utc)-datetime.fromisoformat(record['created_at'])).total_seconds()>1800:raise PermissionError('Expired request.')
        # Session locks survive the intent update and pre-operation backup commits.
        if not catalog.execute('SELECT pg_try_advisory_lock(79432190) AS locked').fetchone()['locked']:
            if not record.get('execution'):update(catalog,event['id'],record,'failed')
            raise RuntimeError('Database maintenance or Crawl is running.')
        try:
            event=_find(catalog,token);record=json.loads(event['reason'])
            if record['state'] not in ('starting','running','unknown'):return {'status':'ok','already_completed':True}
            header=rows=sequences=None
            if action=='restore':
                backup=catalog.execute("SELECT reason FROM events WHERE CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'backup_id'=%s ORDER BY id DESC LIMIT 1",('{"kind":"'+KIND+'",%',record['backup_id'])).fetchone()
                if not backup:raise ValueError('Backup missing.')
                backup=json.loads(backup['reason'])
                if backup['target']!=target or backup.get('deleted_at'):raise ValueError('Backup target differs or expired.')
                ref=ObjectReference(**backup['object'])
                if ref.scope!=('content' if target=='chronicle' else 'accounts') or ref.content_type!='application/gzip':raise ValueError('Wrong archive scope.')
                progress('verify_archive');header,rows,sequences=load(storage.get(ref),target,backup['sha256'])
                if target=='accounts':
                    from ygc.cloud_avatar import decode_reference
                    for user in rows['account_records']:
                        if user['avatar_storage_path']:storage.get(decode_reference(user['avatar_storage_path']))
                if target=='chronicle':
                    from ygc.cloud_content_media import verify_restored_media
                    verify_restored_media(storage,rows['media_assets'])
            with connect(settings,'accounts') as source:
                source.execute("SET LOCAL lock_timeout='5s'")
                # Blocks writes and row-locking projection workers; plain identity reads remain possible.
                source.execute('LOCK TABLE account_records IN EXCLUSIVE MODE')
                actor=source.execute('SELECT * FROM account_records WHERE app_user_id=%s',(record['actor'],)).fetchone()
                PostgresAccounts._active(actor)
                if actor['role']!='admin':raise PermissionError('Administrator revoked.')
                mode=catalog.execute('SELECT mode FROM settings WHERE id=1 FOR SHARE').fetchone()['mode']
                if mode=='normal':raise PermissionError('Maintenance mode required.')
                record['execution']=execution
                update(catalog,event['id'],record,'running')
                # Never proceed when the protective save failed. Do not prune the selected archive here.
                progress('safety_backup');save(settings,storage,target,execution,source='pre_restore')
                catalog.execute('SELECT mode FROM settings WHERE id=1 FOR SHARE')
                if catalog.execute('SELECT mode FROM settings WHERE id=1').fetchone()['mode']=='normal':raise PermissionError('Maintenance mode changed.')
                catalog.execute('SELECT pg_advisory_xact_lock(%s)',(79432100+TARGETS.index(target),))
                current=[dict(row) for row in source.execute('SELECT * FROM account_records ORDER BY id')]
                progress('apply_data')
                if target=='accounts':
                    if action=='restore':restore_accounts(source,header,rows,sequences)
                    else:
                        # Reset test/social data, retaining registration, identity reservations and Admin authority.
                        for table in ('account_direct_messages','account_user_follows','local_sessions'):
                            source.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(table)))
                    source.commit()
                elif target=='operations':
                    # Mode, audit/catalog and pending requests survive an Operations rewind/reset.
                    if action=='restore':
                        from ygc.db.postgres import recorded_schema,validate_schema
                        revision=catalog.execute('SELECT version,checksum FROM ygc_schema_version WHERE id=1').fetchone()
                        if revision['version']!=header['schema_version'] or revision['checksum']!=header['schema_checksum']:raise ValueError('Restore schema differs.')
                        validate_schema(catalog,recorded_schema(target,revision))
                    for table in ('auto_crawl','backup_schedules','backup_settings','paused_review_answers','review_settings'):
                        catalog.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(table)))
                        if action=='restore':
                            from ygc.cloud_db_restore import insert
                            insert(catalog,table,header['tables'][table],rows[table])
                    if action=='reset':
                        catalog.execute("INSERT INTO auto_crawl VALUES(1,0,'electric_acoustic',1950,1980,3600,0)")
                        catalog.execute('INSERT INTO backup_settings VALUES(1,10)')
                        catalog.execute('INSERT INTO review_settings VALUES(1,0)')
                        for name in TARGETS:catalog.execute('INSERT INTO backup_schedules(target,enabled,interval_hours,generations,next_run) VALUES(%s,0,24,10,0)',(name,))
                    # Restoring a control DB never silently reactivates automated writers.
                    catalog.execute('UPDATE auto_crawl SET enabled=0');catalog.execute('UPDATE review_settings SET enabled=0')
                    catalog.execute('UPDATE backup_schedules SET enabled=0,next_run=0')
                else:
                    with connect(settings,target) as dest:
                        dest.execute("SET LOCAL lock_timeout='5s'")
                        if target=='chronicle':dest.execute('SELECT pg_advisory_xact_lock(79432002)')
                        if action=='reset':
                            from ygc.db.postgres import recorded_schema
                            from ygc.cloud_db_restore import order
                            revision=dest.execute('SELECT version,checksum FROM ygc_schema_version WHERE id=1').fetchone()
                            tables=recorded_schema(target,revision)['tables']
                            dest.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(sql.SQL(',').join(map(sql.Identifier,tables))))
                            ordered,_=order(dest,tables)
                            for table in reversed(ordered):dest.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(table)))
                            if target=='chronicle':
                                accounts=PostgresAccounts(settings)
                                for account in current:accounts._apply_projection(dest,account,force_rebuild=True)
                        else:replace_content(dest,header,rows,sequences,current)
                source.commit()
            if target=='accounts':
                progress('reconcile_accounts');PostgresAccounts(settings).reconcile_projection()
            update(catalog,event['id'],record,'succeeded')
            return {'status':'ok','target':target,'action':action,'safety_backup':True}
        except Exception:
            catalog.rollback()
            latest=_find(catalog,token)
            if latest:update(catalog,event['id'],json.loads(latest['reason']),'failed')
            raise
        finally:
            catalog.execute('SELECT pg_advisory_unlock(79432190)')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--confirm-project',required=True)
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--request-id');group.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv);storage=None;stage='configuration'
    def progress(value):
        nonlocal stage
        stage=value;print(json.dumps({'stage':value}),flush=True)
    try:
        project=os.environ.get('YGC_GCP_PROJECT_ID','')
        if args.confirm_project!=project or os.environ.get('CLOUD_RUN_JOB')!='ygc-staging-db-maintenance' or os.environ.get('K_SERVICE') or os.environ.get('CLOUD_RUN_TASK_COUNT','1')!='1' or os.environ.get('YGC_DATABASE_BACKEND')!='postgres':raise ValueError('Confirmed single-task maintenance Job required.')
        settings=PostgresSettings.from_environment()
        if not settings.host.startswith('/cloudsql/'+project+':'):raise ValueError('Project mismatch.')
        storage=CloudStorage(StorageSettings.from_environment(project))
        if args.check_only:
            from ygc.db.postgres import status
            for target in TARGETS:status(settings,target)
            result={'status':'ok','checked_targets':4,'data_changed':False}
        else:result=perform(settings,storage,args.request_id,os.environ.get('CLOUD_RUN_EXECUTION',''),progress)
        print(json.dumps(result));return 0
    except Exception:
        print(json.dumps({'status':'failed','stage':stage}),file=sys.stderr);return 1
    finally:
        if storage is not None:storage.close()


if __name__=='__main__':raise SystemExit(main())
