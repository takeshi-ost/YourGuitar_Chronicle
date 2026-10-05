"""Admin Crawl configuration and durable fixed-Job requests."""
from datetime import datetime,timezone,timedelta
import json
import time
from ygc.cloud_backup_control import BackupJobClient,BackupBusy,request_id
from ygc.cloud_crawl_job import KIND,find,configured_limit,validate_limit,DEFAULT_SUMMARY_LIMIT
from ygc.db.postgres import connect


def validate(low,high,hours):
    if type(low) is not int or type(high) is not int or type(hours) is not int or not 1800<=low<=high<=2100 or not 1<=hours<=168:raise ValueError('Invalid Crawl settings.')


def public(record):
    result={k:record[k] for k in ('request_id','state','created_at','source','year_min','year_max')}
    result['retry_allowed']=datetime.now(timezone.utc)-datetime.fromisoformat(record['created_at'])>timedelta(minutes=30)
    if result['retry_allowed'] and result['state'] in ('starting','running','unknown'):result['state']='unknown'
    return result


class CrawlJobClient(BackupJobClient):
    def __init__(self,project,region,**kwargs):
        super().__init__(project,region,**kwargs);self.job=self.prefix+'/jobs/ygc-staging-reverb-crawl'
    def start(self,target,token):
        if target!='chronicle':raise ValueError('Chronicle only.')
        request_id(token)
        response=self.session.post('https://run.googleapis.com/v2/'+self.job+':run',json={'overrides':{'containerOverrides':[{'args':['-m','ygc.cloud_crawl_job','--confirm-project='+self.project,'--request-id='+token]}]}},timeout=10)
        response.raise_for_status();name=response.json()['name'];self._operation(name);return name


class CrawlControl:
    def __init__(self,operations,client=None):self.operations=operations;self.client=client
    def details(self,actor):
        with self.operations.access('admin_read',actor) as (con,mode,account):
            row=dict(con.execute('SELECT * FROM auto_crawl WHERE id=1').fetchone())
            latest=con.execute('SELECT reason FROM events WHERE reason LIKE %s ORDER BY id DESC LIMIT 1',('{"kind":"'+KIND+'",%',)).fetchone()
            row['summary_limit']=configured_limit(con)
            row['enabled']=bool(row['enabled']);row['interval_hours']=row.pop('interval_seconds')//3600
            row.pop('id');row['available']=self.client is not None
            row['request']=public(json.loads(latest['reason'])) if latest else {'state':'idle'}
            started=con.execute("SELECT reason FROM events WHERE CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'started_at' IS NOT NULL ORDER BY id DESC LIMIT 1",('{"kind":"'+KIND+'",%',)).fetchone()
            row['last_at']=json.loads(started['reason'])['started_at'] if started else None
            with connect(self.operations.settings,'chronicle') as content:
                rows=content.execute("SELECT id,started_at,finished_at,status,phase,category,year_min,year_max,pages_discovered,pages_fetched,observations_created FROM crawl_runs WHERE source_site='reverb' ORDER BY id DESC LIMIT 20").fetchall()
            row['runs']=[dict(r) for r in rows];return row
    def configure(self,actor,data):
        if not isinstance(data,dict) or set(data)!={'year_min','year_max','interval_hours','enabled','summary_limit'} or type(data['enabled']) is not bool:raise ValueError('Invalid settings.')
        validate(data['year_min'],data['year_max'],data['interval_hours']);validate_limit(data['summary_limit'])
        if data['enabled'] and self.client is None:raise ValueError('Crawl Job not configured.')
        with self.operations.access('admin_write',actor) as (con,mode,account):
            con.execute("UPDATE auto_crawl SET category='electric_acoustic',year_min=%s,year_max=%s,interval_seconds=%s,enabled=%s,next_run=%s WHERE id=1",(data['year_min'],data['year_max'],data['interval_hours']*3600,int(data['enabled']),(int(time.time()//3600)+data['interval_hours']+1)*3600))
            con.execute('INSERT INTO events(occurred_at,mode,reason) VALUES(%s,%s,%s)',(datetime.now(timezone.utc).isoformat(),mode['mode'],json.dumps(dict(action='crawl_settings',actor=actor,**data))))
        return self.details(actor)
    def start(self,actor,data):
        if self.client is None:raise ValueError('Crawl Job not configured.')
        if not isinstance(data,dict) or set(data)!={'request_id','year_min','year_max','summary_limit'}:raise ValueError('Invalid Crawl request.')
        token=request_id(data['request_id']);validate(data['year_min'],data['year_max'],1);validate_limit(data['summary_limit'])
        with self.operations.access('admin_write',actor) as (con,mode,account):
            previous=find(con,token)
            if previous:
                record=json.loads(previous['reason'])
                if record['actor']!=actor or any(record[k]!=data[k] for k in ('year_min','year_max')) or record.get('summary_limit',DEFAULT_SUMMARY_LIMIT)!=data['summary_limit']:raise ValueError('UUID reused.')
                return public(record)
            pending=con.execute("""SELECT 1 FROM events WHERE
             (reason LIKE %s OR reason LIKE %s) AND CASE WHEN reason LIKE '{"kind":%%' THEN reason::jsonb ELSE NULL END ->>'state' IN ('starting','running','unknown')
             AND CASE WHEN reason LIKE '{"kind":%%' THEN reason::jsonb ELSE NULL END ->>'created_at'>%s LIMIT 1""",('{"kind":"'+KIND+'",%','{"kind":"db_maintenance_request_v1",%',(datetime.now(timezone.utc)-timedelta(minutes=30)).isoformat())).fetchone()
            if pending:raise BackupBusy()
            record=dict(kind=KIND,request_id=token,actor=actor,state='starting',source='manual',created_at=datetime.now(timezone.utc).isoformat(),year_min=data['year_min'],year_max=data['year_max'],summary_limit=data['summary_limit'])
            event=con.execute('INSERT INTO events(occurred_at,mode,reason) VALUES(%s,%s,%s) RETURNING id',(record['created_at'],mode['mode'],json.dumps(record,separators=(',',':')))).fetchone();con.commit()
            try:record['operation']=self.client.start('chronicle',token);record['state']='running'
            except Exception:record['state']='unknown'
            worker=json.loads(con.execute('SELECT reason FROM events WHERE id=%s FOR UPDATE',(event['id'],)).fetchone()['reason'])
            if worker.get('execution') or worker['state'] in ('succeeded','failed'):record=worker
            con.execute('UPDATE events SET reason=%s WHERE id=%s',(json.dumps(record,separators=(',',':')),event['id']))
            return public(record)
