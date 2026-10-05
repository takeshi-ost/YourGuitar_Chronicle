"""Admin-confirmed maintenance requests; never accept a raw archive or cloud resource."""
from datetime import datetime,timezone,timedelta
import json
from ygc.cloud_backup_control import BackupJobClient,BackupBusy,request_id
from ygc.cloud_maintenance_job import REQUEST_KIND
from ygc.db.postgres import TARGETS,connect


class MaintenanceModeRequired(Exception):pass


class MaintenanceJobClient(BackupJobClient):
    def __init__(self,project,region,**kwargs):
        super().__init__(project,region,**kwargs)
        self.job=self.prefix+'/jobs/ygc-staging-db-maintenance'

    def start(self,target,token):
        if target not in TARGETS:raise ValueError('Invalid target.')
        request_id(token)
        response=self.session.post('https://run.googleapis.com/v2/'+self.job+':run',
            json={'overrides':{'containerOverrides':[{'args':['-m','ygc.cloud_maintenance_job','--confirm-project='+self.project,'--request-id='+token]}]}},timeout=10)
        response.raise_for_status();name=response.json()['name'];self._operation(name);return name


def public(record):
    result={key:record[key] for key in ('request_id','target','action','state','created_at')}
    result['retry_allowed']=(datetime.now(timezone.utc)-datetime.fromisoformat(record['created_at'])).total_seconds()>1800
    if result['retry_allowed'] and result['state'] in ('starting','running','unknown'):result['state']='unknown'
    return result


class MaintenanceControl:
    def __init__(self,operations,client):self.operations=operations;self.client=client

    def start(self,actor,data):
        if not isinstance(data,dict) or set(data)!={'target','action','backup_id','request_id','confirmation'}:raise ValueError('Invalid request.')
        target=data['target'];action=data['action'];token=request_id(data['request_id'])
        if target not in TARGETS or action not in ('restore','reset') or data['confirmation']!=target:raise ValueError('Confirm the selected database name.')
        if action=='restore':request_id(data['backup_id'])
        elif data['backup_id'] is not None:raise ValueError('Reset does not select an archive.')
        with self.operations.access('admin_write',actor) as (con,mode,account):
            if mode['mode']=='normal':raise MaintenanceModeRequired()
            previous=con.execute("SELECT reason FROM events WHERE CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'request_id'=%s ORDER BY id DESC LIMIT 1",('{"kind":"'+REQUEST_KIND+'",%',token)).fetchone()
            if previous:
                record=json.loads(previous['reason'])
                if any(record[key]!=data[key] for key in ('target','action','backup_id')) or record['actor']!=str(actor):raise ValueError('UUID reused for another request.')
                return public(record)
            pending=con.execute("""SELECT 1 FROM events WHERE CASE WHEN (reason LIKE %s OR reason LIKE '{"kind":"reverb_crawl_request_v1",%%') THEN reason::jsonb ELSE NULL END ->>'state' IN ('starting','running','unknown')
              AND CASE WHEN (reason LIKE %s OR reason LIKE '{"kind":"reverb_crawl_request_v1",%%') THEN reason::jsonb ELSE NULL END ->>'created_at'>%s LIMIT 1""",('{"kind":"'+REQUEST_KIND+'",%','{"kind":"'+REQUEST_KIND+'",%',(datetime.now(timezone.utc)-timedelta(minutes=30)).isoformat())).fetchone()
            if pending:raise BackupBusy()
            record={'kind':REQUEST_KIND,'request_id':token,'actor':str(actor),'target':target,'action':action,'backup_id':data['backup_id'],'state':'starting','created_at':datetime.now(timezone.utc).isoformat()}
            row=con.execute('INSERT INTO events(occurred_at,mode,reason) VALUES(%s,%s,%s) RETURNING id',(record['created_at'],mode['mode'],json.dumps(record,separators=(',',':')))).fetchone()
            con.commit()
            try:record['operation']=self.client.start(target,token);record['state']='running'
            except Exception:record['state']='unknown'
            # Preserve a completion recorded by a quickly finished worker.
            current=con.execute('SELECT reason FROM events WHERE id=%s FOR UPDATE',(row['id'],)).fetchone()
            worker=json.loads(current['reason'])
            if worker.get('execution') or worker['state'] in ('succeeded','failed'):record=worker
            con.execute('UPDATE events SET reason=%s WHERE id=%s',(json.dumps(record,separators=(',',':')),row['id']))
            return public(record)

    def status(self,actor,target):
        if target not in TARGETS:raise ValueError('Invalid target.')
        # Route already verifies current identity/role; metadata polling takes no source row lock
        # that could block behind the maintenance worker's data-replacement fence.
        with connect(self.operations.settings,'operations') as con:
            con.execute('SET TRANSACTION READ ONLY')
            row=con.execute("SELECT reason FROM events WHERE CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'target'=%s ORDER BY id DESC LIMIT 1",('{"kind":"'+REQUEST_KIND+'",%',target)).fetchone()
            return public(json.loads(row['reason'])) if row else {'target':target,'state':'idle'}
