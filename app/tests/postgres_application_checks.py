"""Real intake transactions: canonical applicants, private photos and no Owner change."""
from dataclasses import replace
from datetime import datetime,timezone
import json
from psycopg import errors,sql
from ygc.cloud_applications import CloudApplications,verify_restored_applications
from ygc.cloud_content_media import MediaConflict
from ygc.db.postgres import connect
from test_cloud_avatar import png


def run(app,accounts,operations,store,aid,bid):
    def rejected(kind,fn):
        try:fn()
        except kind:return
        raise AssertionError('Expected '+kind.__name__)
    before=operations.details(aid)
    operations.set_mode(aid,mode='normal',message='',version=before['version'])
    accounts.drain_projection();service=CloudApplications(app,operations,store)
    assert service.list(bid)['can_write'] is True
    payload=dict(manufacturer='Fender',serial_number='INTAKE001',model='Intake test',finish='',year='',occurred_at='2020-01-01',body='Private explanation')
    listing=service.start(bid,dict(kind='listing',payload=payload));revision=listing['revision']
    assert listing['status']=='draft' and len(listing['challenge'])==8
    assert service.start(bid,dict(kind='listing',payload=payload))['revision']==revision
    with connect(app,'chronicle') as con:
        initial_claims=con.execute('SELECT COUNT(*) AS n FROM claims').fetchone()['n']
        initial_individuals=con.execute('SELECT COUNT(*) AS n FROM individuals').fetchone()['n']
    rejected(LookupError,lambda:service.upload(aid,revision,'closeup',png(),'image/png'))
    rejected(ValueError,lambda:service.submit(bid,revision,dict(acquisition_date='2020-01-01',body=payload['body'])))
    # Failure to record the photo event rolls back its DB reference and removes
    # only the uncommitted object; already saved immutable photos survive.
    owner=replace(app,user='postgres');object_count=len(store.objects)
    with connect(owner,'chronicle') as con:con.execute(sql.SQL('REVOKE INSERT ON acquire_application_events FROM {}').format(sql.Identifier(app.user)))
    try:rejected(errors.InsufficientPrivilege,lambda:service.upload(bid,revision,'closeup',png(),'image/png'))
    finally:
        with connect(owner,'chronicle') as con:con.execute(sql.SQL('GRANT INSERT ON acquire_application_events TO {}').format(sql.Identifier(app.user)))
    assert len(store.objects)==object_count
    service.upload(bid,revision,'closeup',png(),'image/png');service.upload(bid,revision,'overview',png(),'image/png')
    assert service.image(bid,revision,'closeup').startswith(b'\xff\xd8')
    rejected(LookupError,lambda:service.image(aid,revision,'closeup'))
    data=dict(acquisition_date='2020-01-01',body=payload['body'])
    assert service.submit(bid,revision,data)['status']=='pending'
    assert service.submit(bid,revision,data)['status']=='pending'
    rejected(ValueError,lambda:service.upload(bid,revision,'overview',png(),'image/png'))
    with connect(app,'chronicle') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM claims').fetchone()['n']==initial_claims
        assert con.execute('SELECT COUNT(*) AS n FROM individuals').fetchone()['n']==initial_individuals
        row=con.execute('SELECT * FROM acquire_applications WHERE revision=%s',(revision,)).fetchone()
        verify_restored_applications(store,[row])
        assert row['lease_token'] is None and row['claim_id'] is None
        uid=con.execute('SELECT id FROM users WHERE app_user_id=%s',(aid,)).fetchone()['id']
        guitar=con.execute("INSERT INTO individuals(manufacturer,normalized_manufacturer,serial_number,normalized_serial,current_owner_user_id,created_at,updated_at) VALUES('Fender','fender','INTAKE002','INTAKE002',%s,'now','now') RETURNING id",(uid,)).fetchone()['id']
    rejected(ValueError,lambda:service.start(aid,dict(kind='acquire',individual_id=str(guitar))))
    acquire=service.start(bid,dict(kind='acquire',individual_id=str(guitar)));other=acquire['revision']
    assert service.start(bid,dict(kind='acquire',individual_id=str(guitar)))['revision']==other
    service.upload(bid,other,'closeup',png(),'image/png');service.upload(bid,other,'overview',png(),'image/png')
    assert service.submit(bid,other,dict(acquisition_date='2020-01-01',body='Acquire'))['status']=='pending'
    with connect(app,'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',(guitar,)).fetchone()['current_owner_user_id']==uid
        assert not con.execute('SELECT 1 FROM claims WHERE individual_id=%s',(guitar,)).fetchone()
    assert service.cancel(bid,other)['status']=='cancelled'
    assert service.cancel(bid,other)['status']=='cancelled'
    rejected(ValueError,lambda:service.submit(bid,other,data))
    # All normal intake respects maintenance, including the Admin acting as an
    # applicant. Administrative console actions have their separate bypass.
    for mode in ('read_only','offline','admin_only'):
        state=operations.details(aid);operations.set_mode(aid,mode=mode,message='test',version=state['version'])
        rejected(PermissionError,lambda:service.start(bid,dict(kind='listing',payload=payload|{'serial_number':'MODE001'})))
        rejected(PermissionError,lambda:service.cancel(bid,revision))
        if mode=='read_only':
            assert service.list(bid)['items'] and service.list(bid)['can_write'] is False
            assert service.list(aid)['can_write'] is False
            assert service.image(bid,revision,'overview').startswith(b'\xff\xd8')
            rejected(PermissionError,lambda:service.cancel(aid,revision))
        else:
            rejected(PermissionError,lambda:service.list(bid))
            rejected(PermissionError,lambda:service.image(bid,revision,'overview'))
        if mode=='admin_only':assert service.list(aid)['can_write'] is True
    state=operations.details(aid);operations.set_mode(aid,mode='normal',message='',version=state['version'])
    assert service.list(bid)['can_write'] is True
    with connect(app,'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        rejected(MediaConflict,lambda:service.cancel(bid,revision))
    accounts.update_profile(bid,dict(bio='Application projection pending'))
    rejected(ValueError,lambda:service.cancel(bid,revision));accounts.drain_projection()
    expired=service.start(bid,dict(kind='listing',payload=payload|{'serial_number':'EXPIRE001'}))
    with connect(app,'chronicle') as con:con.execute('UPDATE acquire_applications SET expires_at=0 WHERE revision=%s',(expired['revision'],))
    rejected(ValueError,lambda:service.upload(bid,expired['revision'],'closeup',png(),'image/png'))
    assert next(row for row in service.list(bid)['items'] if row['revision']==expired['revision'])['status']=='expired'
    # The owner-only fixture above intentionally has no identity Claims; remove
    # it before the independent restore suite enforces complete identity Claims.
    with connect(app,'chronicle') as con:
        con.execute('DELETE FROM acquire_application_events WHERE revision=%s',(other,))
        con.execute('DELETE FROM acquire_applications WHERE revision=%s',(other,))
        con.execute('DELETE FROM individuals WHERE id=%s',(guitar,))
    state=operations.details(aid);operations.set_mode(aid,mode=before['mode'],message=before['message'],version=state['version'])
    print('PostgreSQL applications: intake-only, idempotence, private photos, event rollback, canonical projection, expiry, cancellation and mode/mutex fencing passed.')
