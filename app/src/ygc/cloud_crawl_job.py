"""IAM-only bounded Reverb increment; save only Chronicle before any content write."""
import argparse
from datetime import datetime,timezone,timedelta
import json
import os
import sys
import time
import uuid
from ygc.db.postgres import PostgresSettings,connect,status
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_crawl import reserve_automation,PostgresCrawlRepository
from ygc.cloud_storage import CloudStorage,StorageSettings
from ygc.cloud_backup_job import save
from ygc.cloud_backup_policy import prune
from ygc.collectors.reverb import ReverbAPICollector
from ygc.incremental_crawl import advance_program,program_status,restart_program

KIND='reverb_crawl_request_v1'
SUMMARY_LIMIT=400


def find(con,token):
    return con.execute("SELECT id,reason FROM events WHERE CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'request_id'=%s ORDER BY id DESC LIMIT 1",('{"kind":"'+KIND+'",%',token)).fetchone()


def update(con,event,record,state):
    record['state']=state
    con.execute('UPDATE events SET reason=%s WHERE id=%s',(json.dumps(record,separators=(',',':')),event))
    con.commit()


def perform(settings,storage,collector,execution,token=None,progress=lambda stage:None):
    with connect(settings,'operations') as catalog:
        if token is None:
            pending=catalog.execute("""SELECT 1 FROM events WHERE (reason LIKE %s OR reason LIKE %s)
              AND CASE WHEN reason LIKE '{"kind":%%' THEN reason::jsonb ELSE NULL END ->>'state' IN ('starting','running','unknown')
              AND CASE WHEN reason LIKE '{"kind":%%' THEN reason::jsonb ELSE NULL END ->>'created_at'>%s LIMIT 1""",('{"kind":"'+KIND+'",%','{"kind":"db_maintenance_request_v1",%',(datetime.now(timezone.utc)-timedelta(minutes=30)).isoformat())).fetchone()
            if pending:return {'status':'ok','skipped':True}
        if not catalog.execute('SELECT pg_try_advisory_lock(79432190) AS locked').fetchone()['locked']:
            if token is not None:
                waiting=find(catalog,token)
                if waiting:
                    pending=json.loads(waiting['reason'])
                    if pending['state'] in ('starting','running','unknown') and not pending.get('execution'):update(catalog,waiting['id'],pending,'failed')
            raise RuntimeError('Database maintenance or Crawl is running.')
        catalog.commit();event=None;record=None
        try:
            config=dict(catalog.execute('SELECT * FROM auto_crawl WHERE id=1').fetchone())
            mode=catalog.execute('SELECT mode FROM settings WHERE id=1').fetchone()['mode']
            if token is None:
                if not config['enabled'] or config['next_run']>time.time() or mode!='normal':return {'status':'ok','skipped':True}
                token=str(uuid.uuid4());record=dict(kind=KIND,request_id=token,state='starting',source='scheduled',created_at=datetime.now(timezone.utc).isoformat(),year_min=config['year_min'],year_max=config['year_max'])
                event=catalog.execute('INSERT INTO events(occurred_at,mode,reason) VALUES(%s,%s,%s) RETURNING id',(record['created_at'],mode,json.dumps(record,separators=(',',':')))).fetchone()
            else:
                if str(uuid.UUID(token))!=token:raise ValueError('Invalid request.')
                event=find(catalog,token)
                if not event:raise PermissionError('A persisted Admin request is required.')
                record=json.loads(event['reason'])
                if record['state'] not in ('starting','running','unknown'):return {'status':'ok','already_completed':True}
                if datetime.now(timezone.utc)-datetime.fromisoformat(record['created_at'])>timedelta(minutes=30):raise PermissionError('Expired request.')
                with connect(settings,'accounts') as accounts:
                    actor=accounts.execute('SELECT * FROM account_records WHERE app_user_id=%s',(record['actor'],)).fetchone()
                    PostgresAccounts._active(actor)
                    if actor['role']!='admin':raise PermissionError('Admin revoked.')
            low,high=record['year_min'],record['year_max']
            if type(low) is not int or type(high) is not int or not 1800<=low<=high<=2100:raise ValueError('Invalid years.')
            record['started_at']=datetime.now(timezone.utc).isoformat()
            record['execution']=execution
            update(catalog,event['id'],record,'running')
            progress('safety_backup');save(settings,storage,'chronicle',execution,source='crawl')
            # Accounts gets only a canonical system identity reservation, never a Crawl backup.
            progress('projection');source=reserve_automation(settings);repo=PostgresCrawlRepository(settings,source,record.get('actor'))
            if record['source']=='scheduled' and program_status(repo,'electric_acoustic',low,high)['finished']:
                restart_program(repo,'electric_acoustic',low,high)
            progress('crawl')
            result=advance_program(repo,collector,'electric_acoustic',low,high,_summary_limit=SUMMARY_LIMIT)
            record['counts']={key:value for key,value in result.items() if type(value) is int}
            if record['source']=='scheduled':
                catalog.execute('UPDATE auto_crawl SET next_run=%s WHERE id=1 AND year_min=%s AND year_max=%s AND interval_seconds=%s AND next_run=%s',
                    ((int(time.time()//3600)+config['interval_seconds']//3600)*3600,low,high,config['interval_seconds'],config['next_run']))
            update(catalog,event['id'],record,'succeeded')
            try:prune(settings,storage,'chronicle')
            except Exception:record['retention_pending']=True;update(catalog,event['id'],record,'succeeded')
            return {'status':'ok','saved_before_crawl':True,**record['counts']}
        except Exception:
            catalog.rollback()
            if event and record:update(catalog,event['id'],record,'failed')
            raise
        finally:catalog.execute('SELECT pg_advisory_unlock(79432190)')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--confirm-project',required=True)
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--request-id');group.add_argument('--scheduled',action='store_true');group.add_argument('--check-only',action='store_true');group.add_argument('--probe-only',action='store_true')
    args=parser.parse_args(argv);storage=None;collector=None;stage='configuration'
    def progress(value):
        nonlocal stage
        stage=value;print(json.dumps({'stage':value}),flush=True)
    try:
        project=os.environ.get('YGC_GCP_PROJECT_ID','')
        if args.confirm_project!=project or os.environ.get('CLOUD_RUN_JOB')!='ygc-staging-reverb-crawl' or os.environ.get('K_SERVICE') or os.environ.get('CLOUD_RUN_TASK_COUNT','1')!='1' or os.environ.get('YGC_DATABASE_BACKEND')!='postgres':raise ValueError('Confirmed single-task Crawl Job required.')
        settings=PostgresSettings.from_environment()
        if not settings.host.startswith('/cloudsql/'+project+':'):raise ValueError('Wrong project.')
        storage=CloudStorage(StorageSettings.from_environment(project))
        if args.check_only:
            for target in ('accounts','chronicle','operations'):status(settings,target)
            result={'status':'ok','data_changed':False,'reverb_configured':bool(os.environ.get('REVERB_API_TOKEN','').strip())}
        else:
            collector=ReverbAPICollector(os.environ.get('REVERB_API_TOKEN','').strip(),delay=0.5,max_workers=1)
            if args.probe_only:
                progress('reverb_auth')
                collector._get_json(collector.api_base+'/listings',params={'query':'electric guitar','per_page':1})
                result={'status':'ok','reverb_authenticated':True,'data_changed':False}
            else:result=perform(settings,storage,collector,os.environ.get('CLOUD_RUN_EXECUTION',''),args.request_id,progress)
        print(json.dumps(result));return 0
    except Exception:print(json.dumps({'status':'failed','stage':stage}),file=sys.stderr);return 1
    finally:
        if collector is not None:collector.close()
        if storage is not None:storage.close()


if __name__=='__main__':raise SystemExit(main())
