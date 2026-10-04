"""Independent persistent retention and periodic-save policies."""
from datetime import datetime, timezone
import json
import time
from ygc.db.postgres import TARGETS, connect
from ygc.cloud_storage import ObjectReference


def validate(target, generations, enabled, interval_hours):
    if target not in TARGETS or type(generations) is not int or not 1 <= generations <= 100 or type(enabled) is not bool or type(interval_hours) is not int or not 1 <= interval_hours <= 168:
        raise ValueError('Invalid backup policy.')


def policy(operations, actor, target):
    if target not in TARGETS:raise ValueError('Unknown target.')
    with operations.access('admin_read', actor) as (con, mode, account):
        row=dict(con.execute('SELECT * FROM backup_schedules WHERE target=%s',(target,)).fetchone())
        row['enabled']=bool(row['enabled'])
        row.pop('last_error',None)
        return row


def configure(operations, actor, target, generations, enabled, interval_hours):
    validate(target,generations,enabled,interval_hours)
    with operations.access('admin_write',actor) as (con,mode,account):
        old=con.execute('SELECT * FROM backup_schedules WHERE target=%s FOR UPDATE',(target,)).fetchone()
        next_run=old['next_run'] if bool(old['enabled'])==enabled and old['interval_hours']==interval_hours else (int(time.time()//3600)+interval_hours+1)*3600
        con.execute('UPDATE backup_schedules SET generations=%s,enabled=%s,interval_hours=%s,next_run=%s WHERE target=%s',
                    (generations,int(enabled),interval_hours,next_run,target))
        con.execute('INSERT INTO events(occurred_at,mode,reason) VALUES(%s,%s,%s)',
                    (datetime.now(timezone.utc).isoformat(),mode['mode'],json.dumps({'action':'backup_policy','actor':str(actor),'target':target,'generations':generations,'enabled':enabled,'interval_hours':interval_hours})))
    return policy(operations,actor,target)


def prune(settings,storage,target):
    """Only committed backup objects of one target; never bucket-wide listing/deletion."""
    from ygc.cloud_backup_job import KIND
    from ygc.cloud_db_snapshot import verify_snapshot
    from google.api_core.exceptions import NotFound
    if target not in TARGETS:raise ValueError('Unknown target.')
    deleted=0
    with connect(settings,'operations') as con:
        con.execute('SELECT pg_advisory_xact_lock(%s)',(79432100+TARGETS.index(target),))
        # A queued restore pins its selection while a worker starts and saves its safety copy.
        pending=con.execute("""SELECT reason FROM events WHERE
          CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'state' IN ('starting','running','unknown')
          AND CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'target'=%s""",
          ('{"kind":"db_maintenance_request_v1",%','{"kind":"db_maintenance_request_v1",%',target)).fetchall()
        pinned={json.loads(row['reason']).get('backup_id') for row in pending
                if (datetime.now(timezone.utc)-datetime.fromisoformat(json.loads(row['reason'])['created_at'])).total_seconds()<1800}
        keep=con.execute('SELECT generations FROM backup_schedules WHERE target=%s FOR SHARE',(target,)).fetchone()['generations']
        if type(keep) is not int or not 1<=keep<=100:raise ValueError('Invalid retention.')
        rows=con.execute("""SELECT id,reason FROM events WHERE
          CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'target'=%s
          AND CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>'deleted_at' IS NULL
          ORDER BY id DESC""",('{"kind":"'+KIND+'",%',target,'{"kind":"'+KIND+'",%')).fetchall()
        for row in rows[keep:]:
            record=json.loads(row['reason']);ref=ObjectReference(**record['object'])
            if record['backup_id'] in pinned:continue
            if ref.scope!=('content' if target=='chronicle' else 'accounts') or ref.content_type!='application/gzip':raise ValueError('Wrong archive scope.')
            try:
                verify_snapshot(storage.get(ref),target,record['sha256'])
                storage.delete(ref)
            except NotFound:
                # Reconcile exact-generation deletion whose previous catalog commit was uncertain.
                pass
            record['deleted_at']=datetime.now(timezone.utc).isoformat()
            con.execute('UPDATE events SET reason=%s WHERE id=%s',(json.dumps(record,separators=(',',':')),row['id']))
            deleted+=1
    return deleted
