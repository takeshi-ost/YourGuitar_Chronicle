"""Disposable PostgreSQL restore/reset, identity fencing and protective copies."""
import json
import uuid
from datetime import datetime,timezone
from ygc.db.postgres import connect
from ygc.cloud_backup_job import save,KIND
from ygc.cloud_maintenance_job import perform,REQUEST_KIND
from ygc.cloud_maintenance_control import MaintenanceControl,MaintenanceModeRequired
from unittest.mock import Mock


def run(app,accounts,operations,store,aid,bid):
    def archive(target):
        save(app,store,target,'maintenance-fixture')
        with connect(app,'operations') as con:
            row=con.execute('SELECT reason FROM events WHERE reason LIKE %s ORDER BY id DESC LIMIT 1',('{"kind":"'+KIND+'",%',)).fetchone()
            return json.loads(row['reason'])['backup_id']
    client=Mock();client.start.return_value='private-operation'
    control=MaintenanceControl(operations,client)
    def queue(target,action,backup_id=None):
        token=str(uuid.uuid4());data=dict(target=target,action=action,backup_id=backup_id,request_id=token,confirmation=target)
        first=control.start(aid,data);calls=client.start.call_count
        assert first==control.start(aid,data) and client.start.call_count==calls
        try:control.start(bid,data)
        except PermissionError:pass
        else:raise AssertionError('Member accepted maintenance.')
        return token
    old=archive('chronicle')
    with connect(app,'chronicle') as con:
        added=con.execute("INSERT INTO individuals(manufacturer,model,normalized_manufacturer,created_at,updated_at) VALUES('New','New','new','now','now') RETURNING id").fetchone()['id']
    newer=accounts.ensure_identity(issuer='issuer',subject='after-backup',display_name='New registration')
    accounts.drain_projection()
    token=queue('chronicle','restore',old)
    assert perform(app,store,token,'restore-fixture')['safety_backup']
    assert perform(app,store,token,'repeat-fixture')['already_completed']
    with connect(app,'chronicle') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM individuals').fetchone()['n']==28
        assert con.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n']==3
        following=con.execute("INSERT INTO individuals(manufacturer,model,normalized_manufacturer,created_at,updated_at) VALUES('Later','Later','later','now','now') RETURNING id").fetchone()['id']
        assert following>added
    old_accounts=archive('accounts')
    with connect(app,'accounts') as con:
        before=con.execute('SELECT * FROM account_records WHERE app_user_id=%s',(bid,)).fetchone()
        con.execute("UPDATE account_records SET display_name='Changed',ban_status='silent_ban' WHERE app_user_id=%s",(bid,))
    fourth=accounts.ensure_identity(issuer='issuer',subject='fourth',display_name='Fourth')
    perform(app,store,queue('accounts','restore',old_accounts),'accounts-fixture')
    with connect(app,'accounts') as con:
        restored=con.execute('SELECT * FROM account_records WHERE app_user_id=%s',(bid,)).fetchone()
        assert restored['display_name']==before['display_name'] and restored['ban_status']=='silent_ban'
        assert restored['projection_version']>before['projection_version']
        assert con.execute('SELECT COUNT(*) AS n FROM account_records').fetchone()['n']==4
        assert con.execute('SELECT role FROM account_records WHERE app_user_id=%s',(aid,)).fetchone()['role']=='admin'
    perform(app,store,queue('chronicle','reset'),'reset-fixture')
    with connect(app,'chronicle') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM individuals').fetchone()['n']==0
        assert con.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n']==4
    old_ops=archive('operations')
    with connect(app,'operations') as con:
        con.execute('UPDATE backup_schedules SET enabled=1')
        event_count=con.execute('SELECT COUNT(*) AS n FROM events').fetchone()['n']
        mode=con.execute('SELECT mode FROM settings WHERE id=1').fetchone()['mode']
    perform(app,store,queue('operations','restore',old_ops),'operations-fixture')
    with connect(app,'operations') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM events').fetchone()['n']>event_count
        assert con.execute('SELECT mode FROM settings WHERE id=1').fetchone()['mode']==mode
        assert not con.execute('SELECT 1 FROM backup_schedules WHERE enabled=1').fetchone()
    old_auth=archive('authentication')
    perform(app,store,queue('authentication','restore',old_auth),'authentication-fixture')
    perform(app,store,queue('authentication','reset'),'authentication-reset-fixture')
    perform(app,store,queue('accounts','reset'),'accounts-reset-fixture')
    with connect(app,'accounts') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM identity_links').fetchone()['n']==4
    version=operations.details(aid)['version']
    denied=queue('chronicle','reset')
    operations.set_mode(aid,mode='normal',message='',version=version)
    try:queue('chronicle','reset')
    except MaintenanceModeRequired:pass
    else:raise AssertionError('Normal mode accepted request.')
    try:perform(app,store,denied,'denied-fixture')
    except PermissionError:pass
    else:raise AssertionError('Normal mode accepted reset.')
    version=operations.details(aid)['version']
    operations.set_mode(aid,mode=mode,message='Test',version=version)
    print('PostgreSQL maintenance: independent restore/reset, protective copy, repeat UUID, latest registrations/Admin/BAN, monotonic IDs, retained audit/mode and automation OFF passed.')
