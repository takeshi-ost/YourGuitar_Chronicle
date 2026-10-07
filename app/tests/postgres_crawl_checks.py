"""Reverb pipeline with realistic fixture responses and disposable PostgreSQL."""
from ygc.db.postgres import connect
from ygc.db.postgres_crawl import reserve_automation,PostgresCrawlRepository
from ygc.incremental_crawl import advance_program
from test_incremental_crawl import Collector,_summary
from test_reverb_claim_persistence import _claim_data
from ygc.db.repository import utcnow


def run(app,accounts,operations,storage,aid):
    source=reserve_automation(app)
    assert source==reserve_automation(app)
    registered=accounts.ensure_identity(issuer='crawl-fixture',subject='new',display_name='After Automation')
    assert registered['id']>source
    repo=PostgresCrawlRepository(app,source)
    class SpecificationCollector(Collector):
        def _get_json(self,url,params=None):
            result=super()._get_json(url,params)
            if 'id' in result:result['specifications']={'body':'Ash','pickups':'Three single coils'}
            return result
    collector=SpecificationCollector([{'listings':[_summary(1),_summary(2),dict(_summary(3),product_type='electric-basses')]}])
    result=advance_program(repo,collector,'electric_acoustic',1970,1979)
    assert result['new_individuals']==2 and result['new_observations']==2
    with connect(app,'chronicle') as con:
        items=list(con.execute("SELECT * FROM individuals WHERE normalized_manufacturer='fender' ORDER BY id"))
        assert len(items)==2 and all(r['current_owner_user_id'] is None for r in items)
        assert con.execute("SELECT COUNT(*) AS n FROM claims WHERE claim_type='listing'").fetchone()['n']==2
        assert con.execute('SELECT COUNT(*) AS n FROM claim_spec_items').fetchone()['n']==4
        assert con.execute('SELECT COUNT(*) AS n FROM observations').fetchone()['n']==0
        assert con.execute("SELECT COUNT(*) AS n FROM crawl_runs WHERE status='ok'").fetchone()['n']==1
    # New external ID for a known instrument records Acquire and source Evidence.
    claim=_claim_data(listing_id='later',serial='524431')
    provenance=dict(source_site='reverb',source_listing_id='later',source_url='https://reverb.com/item/later',observed_at=utcnow(),created_at=utcnow())
    assert repo.persist_reverb_listing_claim(claim,provenance)['created']
    assert not repo.persist_reverb_listing_claim(claim,provenance)['created']
    with connect(app,'chronicle') as con:
        row=con.execute("SELECT * FROM claims WHERE claim_type='ownership' AND ownership_kind='acquire' ORDER BY id DESC LIMIT 1").fetchone()
        assert row['verification_status']=='positive' and row['author_user_id']==source
    unavailable=repo.record_reverb_unavailable('later')
    assert unavailable['created'] and unavailable['owner_lost']
    assert not repo.record_reverb_unavailable('later')['created']
    from ygc.cloud_guitars import CloudGuitars,GuitarMissing
    from unittest.mock import patch
    browser=CloudGuitars(app,operations)
    history=browser.chronicle(aid,items[0]['id'],limit=1)
    assert history['total']>=2 and len(history['items'])==1 and history['next_after'] is not None
    following=browser.chronicle(aid,items[0]['id'],after=history['next_after'],limit=1)
    assert following['total']==history['total'] and following['items'][0]['id']<history['items'][0]['id']
    full=browser.chronicle(aid,items[0]['id'])
    listing=[r for r in full['items'] if r['claim_type']=='listing'][0]
    assert listing['author_user_id']==source and listing['effective_status']=='active'
    assert any(item['field_name']=='serial_number' for item in listing['items'])
    assert not {'payload_json','source_url','image_url','evidence','admin_verification'} & set(listing)
    assert all(item['field_name'] not in ('source_url','image_url') for item in listing['items'])
    from ygc.db.postgres import connect as real_connect
    with real_connect(app,'chronicle') as con:
        before=con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',(items[0]['id'],)).fetchone()['current_owner_user_id']
    browser.chronicle(aid,items[0]['id'])
    with real_connect(app,'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',(items[0]['id'],)).fetchone()['current_owner_user_id']==before
    # Admin force verification uses the shared business transaction and audit.
    from ygc.claim_revision import ClaimConflict
    def target_claim():return next(r for r in browser.chronicle(aid,items[0]['id'])['items'] if r['claim_type']=='specification')
    target=target_claim();cid=target['id'];individual=items[0]['id'];previous=target['verification_status'];token=target['revision']
    with connect(app,'chronicle') as con:audits=con.execute('SELECT COUNT(*) AS n FROM claim_admin_actions').fetchone()['n']
    for mode in ('normal','read_only','offline','admin_only'):
        state=operations.details(aid);operations.set_mode(aid,mode=mode,message='fixture',version=state['version'])
        current=target_claim()
        browser.moderate(aid,individual,cid,action='negative',revision=current['revision'])
        current=target_claim();assert current['verification_status']=='negative'
        browser.moderate(aid,individual,cid,action='unverified',revision=current['revision'])
    try:browser.moderate(aid,individual,cid,action='positive',revision=token)
    except ClaimConflict:pass
    else:raise AssertionError('Stale decision accepted')
    with connect(app,'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        try:browser.moderate(aid,individual,cid,action='positive',revision=target_claim()['revision'])
        except ClaimConflict:pass
        else:raise AssertionError('Concurrent maintenance accepted')
    try:browser.moderate(registered['app_user_id'],individual,cid,action='positive',revision=target_claim()['revision'])
    except PermissionError:pass
    else:raise AssertionError('Non-admin write accepted')
    browser.moderate(aid,individual,cid,action=previous,revision=target_claim()['revision'])
    with connect(app,'chronicle') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM claim_admin_actions').fetchone()['n']==audits+9
        audit=con.execute('SELECT actor FROM claim_admin_actions WHERE claim_id=%s ORDER BY id DESC LIMIT 1',(cid,)).fetchone()
        assert audit['actor']=='identity-platform:'+aid
    state=operations.details(aid);operations.set_mode(aid,mode='offline',message='fixture',version=state['version'])
    print('PostgreSQL Admin verification: all modes, audit, stale decision, maintenance mutex and non-admin rejection passed.')
    print('PostgreSQL Chronicle read: Listing/Specification/Ownership, fixed fields, source privacy, descending cursor and unchanged owner passed.')
    print('PostgreSQL Crawl: canonical non-login Automation ID, mixed-scope filtering, durable cursor/log, Listing/Evidence, duplicate/relisting Acquire and Lost passed.')
    # A registered Owner is not displaced by a new external listing.
    # The initial crawl is dated at execution time. Keep these later events on
    # that UTC day so increasing Claim IDs establish their intended order.
    owner_date=utcnow()[:10]
    with repo.connect() as con:
        target=items[1]['id']
        cur=con.execute("""INSERT INTO claims(individual_id,author_user_id,claim_type,field_name,value_text,ownership_kind,ownership_source,
         verification_status,occurred_at,created_at,updated_at) VALUES(?,?,'ownership','owner',?,'acquire','user','positive',?,'now','now')""",(target,registered['id'],str(registered['id']),owner_date))
        con.execute("INSERT INTO claim_source_evidence(claim_id,evidence_type,effective_date,created_at) VALUES(?,'acquisition_date',?,'now')",(cur.lastrowid,owner_date))
        snapshot=repo._rebuild_individual_snapshot_in_connection(con,target)
        assert str(snapshot['current_owner_user_id'])==str(registered['id'])
    claim=_claim_data(listing_id='owner-pending',serial='524432');provenance.update(source_listing_id='owner-pending',source_url='https://reverb.com/item/owner-pending',observed_at=owner_date)
    pending=repo.persist_reverb_listing_claim(claim,provenance)
    assert pending['verification_status']=='unverified'
    with connect(app,'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',(target,)).fetchone()['current_owner_user_id']==registered['id']
    assert repo.record_reverb_unavailable('owner-pending')['reason']=='not_current_external_source'
    # Admin profile editing uses the same durable projection and keeps ownership IDs stable.
    from ygc.cloud_users import CloudUsers
    users=CloudUsers(app,operations);profile=users.detail(aid,registered['id'])
    users.edit_profile(aid,registered['id'],dict(revision=profile['profile_revision'],fields=dict(display_name='Renamed Owner',location_country='Japan',location_region='Tokyo',bio='Profile test')))
    assert users.detail(aid,registered['id'])['display_name']=='Renamed Owner'
    accounts.drain_projection()
    with connect(app,'chronicle') as con:
        snapshot=con.execute('SELECT current_owner_user_id,current_owner_name FROM individuals WHERE id=%s',(target,)).fetchone()
        assert snapshot['current_owner_user_id']==registered['id'] and snapshot['current_owner_name']=='Renamed Owner'
    assert target in {r['id'] for r in users.guitars(aid,registered['id'],kind='owned')['items']}
    previous_mode=operations.details(aid)
    operations.set_mode(aid,mode='normal',message='Self profile test',version=previous_mode['version'])
    own=users.own_profile(registered['app_user_id'])
    users.edit_own_profile(registered['app_user_id'],dict(revision=own['profile_revision'],fields={**own['fields'],'display_name':'Self edited Owner'}))
    accounts.drain_projection()
    with connect(app,'chronicle') as con:
        snapshot=con.execute('SELECT current_owner_user_id,current_owner_name FROM individuals WHERE id=%s',(target,)).fetchone()
        assert snapshot['current_owner_user_id']==registered['id'] and snapshot['current_owner_name']=='Self edited Owner'
    operations.set_mode(aid,mode=previous_mode['mode'],message=previous_mode['message'],version=operations.details(aid)['version'])
    assert target in {r['id'] for r in users.guitars(aid,registered['id'],kind='owned')['items']}


    print('PostgreSQL Crawl ownership: external Acquire waits for registered Owner and Lost cannot remove user ownership passed.')

    from unittest.mock import Mock,patch
    from ygc.cloud_crawl_control import CrawlControl
    from ygc.cloud_crawl_job import perform
    from ygc.cloud_backup_job import KIND as BACKUP_KIND
    import json,uuid,time
    client=Mock();client.start.return_value='private-operation';control=CrawlControl(operations,client)
    token=str(uuid.uuid4());data=dict(request_id=token,year_min=1970,year_max=1979,summary_limit=3)
    assert control.start(aid,data)==control.start(aid,data) and client.start.call_count==1
    from ygc.cloud_maintenance_control import MaintenanceControl
    from ygc.cloud_backup_control import BackupBusy
    try:MaintenanceControl(operations,Mock()).start(aid,dict(target='chronicle',action='reset',backup_id=None,request_id=str(uuid.uuid4()),confirmation='chronicle'))
    except BackupBusy:pass
    else:raise AssertionError('Maintenance accepted a pending Crawl.')
    first=Collector()
    with patch('ygc.cloud_crawl_job.advance_program',wraps=advance_program) as advance:
        assert perform(app,storage,first,'fixture-crawl',token)['saved_before_crawl']
        assert advance.call_args.kwargs['_summary_limit']==3
    with connect(app,'operations') as con:
        archives=[json.loads(row['reason']) for row in con.execute('SELECT reason FROM events WHERE reason LIKE %s ORDER BY id',('{"kind":"'+BACKUP_KIND+'",%',))]
        assert archives[-1]['target']=='chronicle' and archives[-1]['source']=='crawl'
    assert perform(app,storage,first,'repeat-crawl',token)['already_completed']
    blocked=str(uuid.uuid4());control.start(aid,dict(data,request_id=blocked));before=Collector()
    with patch('ygc.cloud_crawl_job.save',side_effect=RuntimeError('fixture failure')):
        try:perform(app,storage,before,'failed-save',blocked)
        except RuntimeError:pass
        else:raise AssertionError('Crawl ran after failed safety copy.')
    assert not before.requests
    assert perform(app,storage,before,'scheduled-off')['skipped']
    config=control.configure(aid,dict(year_min=1970,year_max=1979,interval_hours=1,enabled=True,summary_limit=3))
    assert config['enabled'] and config['interval_hours']==1 and control.details(aid)['summary_limit']==3
    with connect(app,'operations') as con:con.execute('UPDATE auto_crawl SET next_run=0')
    assert perform(app,storage,Collector(),'scheduled-maintenance')['skipped']
    version=operations.details(aid)['version'];mode=operations.details(aid)['mode']
    operations.set_mode(aid,mode='normal',message='',version=version)
    assert perform(app,storage,Collector(),'scheduled-due')['saved_before_crawl']
    assert control.details(aid)['next_run']>time.time()
    assert perform(app,storage,Collector(),'scheduled-repeat')['skipped']
    control.configure(aid,dict(year_min=1950,year_max=1980,interval_hours=1,enabled=False,summary_limit=2000))
    operations.set_mode(aid,mode=mode,message='Test',version=operations.details(aid)['version'])
    print('PostgreSQL Crawl Job: persistent intent/retry, Chronicle-only safety save, failed-save network refusal, scheduler OFF/mode/due and next-run fencing passed.')
