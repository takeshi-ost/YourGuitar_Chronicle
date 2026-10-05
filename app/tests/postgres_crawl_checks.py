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
    print('PostgreSQL Crawl: canonical non-login Automation ID, mixed-scope filtering, durable cursor/log, Listing/Evidence, duplicate/relisting Acquire and Lost passed.')
    # A registered Owner is not displaced by a new external listing.
    with repo.connect() as con:
        target=items[1]['id']
        cur=con.execute("""INSERT INTO claims(individual_id,author_user_id,claim_type,field_name,value_text,ownership_kind,ownership_source,
         verification_status,occurred_at,created_at,updated_at) VALUES(?,?,'ownership','owner',?,'acquire','user','positive','2026-10-06','now','now')""",(target,registered['id'],str(registered['id'])))
        con.execute("INSERT INTO claim_source_evidence(claim_id,evidence_type,effective_date,created_at) VALUES(?,'acquisition_date','2026-10-06','now')",(cur.lastrowid,))
        repo._rebuild_individual_snapshot_in_connection(con,target)
    claim=_claim_data(listing_id='owner-pending',serial='524432');provenance.update(source_listing_id='owner-pending',source_url='https://reverb.com/item/owner-pending',observed_at='2026-10-07')
    pending=repo.persist_reverb_listing_claim(claim,provenance)
    assert pending['verification_status']=='unverified'
    with connect(app,'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',(target,)).fetchone()['current_owner_user_id']==registered['id']
    assert repo.record_reverb_unavailable('owner-pending')['reason']=='not_current_external_source'
    print('PostgreSQL Crawl ownership: external Acquire waits for registered Owner and Lost cannot remove user ownership passed.')

    from unittest.mock import Mock,patch
    from ygc.cloud_crawl_control import CrawlControl
    from ygc.cloud_crawl_job import perform
    from ygc.cloud_backup_job import KIND as BACKUP_KIND
    import json,uuid,time
    client=Mock();client.start.return_value='private-operation';control=CrawlControl(operations,client)
    token=str(uuid.uuid4());data=dict(request_id=token,year_min=1970,year_max=1979)
    assert control.start(aid,data)==control.start(aid,data) and client.start.call_count==1
    from ygc.cloud_maintenance_control import MaintenanceControl
    from ygc.cloud_backup_control import BackupBusy
    try:MaintenanceControl(operations,Mock()).start(aid,dict(target='chronicle',action='reset',backup_id=None,request_id=str(uuid.uuid4()),confirmation='chronicle'))
    except BackupBusy:pass
    else:raise AssertionError('Maintenance accepted a pending Crawl.')
    first=Collector()
    assert perform(app,storage,first,'fixture-crawl',token)['saved_before_crawl']
    with connect(app,'operations') as con:
        archives=[json.loads(row['reason']) for row in con.execute('SELECT reason FROM events WHERE reason LIKE %s',('{"kind":"'+BACKUP_KIND+'",%',))]
        assert archives[-1]['target']=='chronicle' and archives[-1]['source']=='crawl'
    assert perform(app,storage,first,'repeat-crawl',token)['already_completed']
    blocked=str(uuid.uuid4());control.start(aid,dict(data,request_id=blocked));before=Collector()
    with patch('ygc.cloud_crawl_job.save',side_effect=RuntimeError('fixture failure')):
        try:perform(app,storage,before,'failed-save',blocked)
        except RuntimeError:pass
        else:raise AssertionError('Crawl ran after failed safety copy.')
    assert not before.requests
    assert perform(app,storage,before,'scheduled-off')['skipped']
    config=control.configure(aid,dict(year_min=1970,year_max=1979,interval_hours=1,enabled=True))
    assert config['enabled'] and config['interval_hours']==1
    with connect(app,'operations') as con:con.execute('UPDATE auto_crawl SET next_run=0')
    assert perform(app,storage,Collector(),'scheduled-maintenance')['skipped']
    version=operations.details(aid)['version'];mode=operations.details(aid)['mode']
    operations.set_mode(aid,mode='normal',message='',version=version)
    assert perform(app,storage,Collector(),'scheduled-due')['saved_before_crawl']
    assert control.details(aid)['next_run']>time.time()
    assert perform(app,storage,Collector(),'scheduled-repeat')['skipped']
    control.configure(aid,dict(year_min=1950,year_max=1980,interval_hours=1,enabled=False))
    operations.set_mode(aid,mode=mode,message='Test',version=operations.details(aid)['version'])
    print('PostgreSQL Crawl Job: persistent intent/retry, Chronicle-only safety save, failed-save network refusal, scheduler OFF/mode/due and next-run fencing passed.')
