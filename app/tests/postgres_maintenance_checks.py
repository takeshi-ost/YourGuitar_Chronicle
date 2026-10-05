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
    # Real image Claim writes use the same authority/snapshot transaction in every
    # mode. Existing source identities remain authoritative during content restore.
    from ygc.cloud_content_media import CloudContentMedia,decode_reference,MediaConflict
    from test_cloud_avatar import png
    from ygc.db.postgres_operations import MODES
    accounts.drain_projection()
    media=CloudContentMedia(app,operations,store)
    with connect(app,'chronicle') as con:
        guitar=con.execute('SELECT id FROM individuals ORDER BY id LIMIT 1').fetchone()['id']
        actor_id=con.execute('SELECT id FROM users WHERE app_user_id=%s',(aid,)).fetchone()['id']
        listing=con.execute("INSERT INTO claims(individual_id,author_user_id,claim_type,occurred_at,created_at,updated_at) VALUES(%s,%s,'listing','2026-01-01','now','now') RETURNING id",(guitar,actor_id)).fetchone()['id']
        for field,value in [('manufacturer','Fender'),('model','Test media'),('serial_number','IMAGE001')]:
            con.execute("INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at) VALUES(%s,%s,%s,'now')",(listing,field,value))
    # An audit failure rolls back Claim/evidence/reference and deletes only the
    # uncommitted image; prior immutable objects remain recoverable.
    from dataclasses import replace
    from psycopg import sql,errors
    owner=replace(app,user='postgres')
    with connect(owner,'chronicle') as con:
        con.execute(sql.SQL('REVOKE INSERT ON claim_admin_actions FROM {}').format(sql.Identifier(app.user)))
    before=len(store.objects)
    try:
        try:media.upload(aid,guitar,png(),'image/png')
        except errors.InsufficientPrivilege:pass
        else:raise AssertionError('Missing image audit allowed a write.')
        assert len(store.objects)==before and store.deleted
        with connect(app,'chronicle') as con:assert con.execute('SELECT COUNT(*) AS n FROM media_assets').fetchone()['n']==0
    finally:
        with connect(owner,'chronicle') as con:con.execute(sql.SQL('GRANT INSERT ON claim_admin_actions TO {}').format(sql.Identifier(app.user)))
    original=operations.details(aid)
    for mode in MODES:
        state=operations.details(aid)
        operations.set_mode(aid,mode=mode,message='Test',version=state['version'])
        result=media.upload(aid,guitar,png(),'image/png')
        assert result['verification_status'] in ('positive','unverified')
        assert media.get(aid,guitar,int(result['media_id'])).startswith(b'\xff\xd8')
        try:media.upload(bid,guitar,png(),'image/png')
        except PermissionError:pass
        else:raise AssertionError('Member accepted Admin image upload.')
    state=operations.details(aid)
    operations.set_mode(aid,mode=original['mode'],message=original['message'],version=state['version'])
    with connect(app,'chronicle') as con:
        image_row=con.execute('SELECT * FROM media_assets ORDER BY id LIMIT 1').fetchone()
        assert con.execute("SELECT COUNT(*) AS n FROM claim_admin_actions WHERE action='media_create'").fetchone()['n']==len(MODES)
        assert con.execute('SELECT COUNT(*) AS n FROM claim_evidence WHERE media_asset_id IS NOT NULL').fetchone()['n']==len(MODES)
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',(guitar,)).fetchone()['current_owner_user_id'] is None
    with connect(app,'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        before=len(store.objects)
        try:media.upload(aid,guitar,png(),'image/png')
        except MediaConflict:pass
        else:raise AssertionError('Image upload overlapped maintenance.')
        assert len(store.objects)==before
    accounts.update_profile(aid,dict(bio='Image projection pending'))
    before=len(store.objects)
    try:media.upload(aid,guitar,png(),'image/png')
    except ValueError:pass
    else:raise AssertionError('Pending account projection accepted image write.')
    assert len(store.objects)==before
    accounts.drain_projection()
    try:media.get(aid,guitar+1,image_row['id'])
    except LookupError:pass
    else:raise AssertionError('Image returned for a different guitar.')
    old=archive('chronicle')
    media.upload(aid,guitar,png(),'image/png')
    assert media.listing(aid,guitar)['total']==str(len(MODES)+1)
    with connect(app,'chronicle') as con:
        added=con.execute("INSERT INTO individuals(manufacturer,model,normalized_manufacturer,created_at,updated_at) VALUES('New','New','new','now','now') RETURNING id").fetchone()['id']
    newer=accounts.ensure_identity(issuer='issuer',subject='after-backup',display_name='New registration')
    accounts.drain_projection()
    reference=decode_reference(image_row['storage_path']);image_bytes=store.objects.pop(reference)
    try:perform(app,store,queue('chronicle','restore',old),'missing-image-fixture')
    except KeyError:pass
    else:raise AssertionError('Missing stored image accepted for restore.')
    with connect(app,'chronicle') as con:
        assert con.execute('SELECT 1 FROM individuals WHERE id=%s',(added,)).fetchone()
    store.objects[reference]=image_bytes
    token=queue('chronicle','restore',old)
    assert perform(app,store,token,'restore-fixture')['safety_backup']
    assert perform(app,store,token,'repeat-fixture')['already_completed']
    with connect(app,'chronicle') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM individuals').fetchone()['n']==28
        assert con.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n']==3
        following=con.execute("INSERT INTO individuals(manufacturer,model,normalized_manufacturer,created_at,updated_at) VALUES('Later','Later','later','now','now') RETURNING id").fetchone()['id']
        assert following>added
    assert media.listing(aid,guitar)['total']==str(len(MODES))
    assert media.get(aid,guitar,image_row['id'])==image_bytes
    # Additional fixture rows exercise media keyset boundaries independently
    # from the upload/Claim atomicity checks above.
    with connect(app,'chronicle') as con:
        for _ in range(22):
            con.execute("INSERT INTO media_assets(individual_id,uploader_user_id,storage_path,mime_type,captured_at,created_at,updated_at) VALUES(%s,%s,%s,'image/jpeg','2026-10-05','now','now')",(guitar,image_row['uploader_user_id'],image_row['storage_path']))
    first=media.listing(aid,guitar)
    second=media.listing(aid,guitar,after=int(first['next_after']))
    assert first['total']=='26' and len(first['items'])==25 and len(second['items'])==1 and second['next_after'] is None
    assert not {r['id'] for r in first['items']} & {r['id'] for r in second['items']}
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
    perform(app,store,queue('chronicle','restore',old),'image-after-reset-fixture')
    assert media.get(aid,guitar,image_row['id'])==image_bytes
    with connect(app,'accounts') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM identity_links').fetchone()['n']==4
        assert con.execute('SELECT role FROM account_records WHERE app_user_id=%s',(aid,)).fetchone()['role']=='admin'
    perform(app,store,queue('chronicle','reset'),'reset-again-fixture')
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
