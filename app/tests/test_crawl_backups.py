import zipfile

import pytest
from fastapi.testclient import TestClient
from ygc import config, web, crawl_backups, operations
from ygc.db.repository import Repository


@pytest.fixture
def environment(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'db.sqlite')
    monkeypatch.setattr(web,'MEDIA_DIR',tmp_path/'media')
    monkeypatch.setattr(web,'_jobs',{})
    monkeypatch.setattr(web,'_active_job_id',None)
    repository=Repository(config.DB_PATH);repository.init_db()
    web.MEDIA_DIR.mkdir();(web.MEDIA_DIR/'image.jpg').write_bytes(b'original-image')
    return repository


ADMIN={'X-YGC-Console-Admin':web.CONSOLE_ADMIN_TOKEN}


def test_retention_and_complete_archives(environment):
    environment.create_user('Original')
    crawl_backups.retention(2)
    first=crawl_backups.create(web.api_export_db)
    with zipfile.ZipFile(crawl_backups.selected(first)) as archive:
        assert {'chronicle.db','manifest.json','media/image.jpg'}<=set(archive.namelist())
    second=crawl_backups.create(web.api_export_db)
    third=crawl_backups.create(web.api_export_db)
    assert [r['name'] for r in crawl_backups.listing()]==[third,second]
    assert not (crawl_backups.directory()/first).exists()
    assert crawl_backups.retention()==2


def test_saved_backup_restore_uses_maintenance_and_safety_backup(environment):
    environment.create_user('Original')
    name=crawl_backups.create(web.api_export_db)
    environment.create_user('Later')
    (web.MEDIA_DIR/'image.jpg').write_bytes(b'changed')
    with TestClient(web.app,base_url='http://127.0.0.1',client=('127.0.0.1',45000)) as client:
        url='/api/admin/operations/backups/'+name+'/restore'
        assert client.get('/api/admin/operations/backups').status_code==403
        assert client.get('/api/admin/operations/backups',headers=ADMIN).status_code==200
        assert client.post(url,headers=ADMIN).status_code==409
        operations.update('read_only','','Restore test',operations.state()['version'])
        response=client.post(url,headers=ADMIN)
        assert response.status_code==200,response.text
        assert [r['display_name'] for r in environment.list_users()]==['Original']
        assert (web.MEDIA_DIR/'image.jpg').read_bytes()==b'original-image'
        assert len(crawl_backups.listing())==2
        assert operations.state()['mode']=='read_only'


def test_crawl_does_not_start_when_backup_fails(environment,monkeypatch):
    def fail(*args):raise OSError('Backup failure')
    monkeypatch.setattr(crawl_backups,'create',fail)
    monkeypatch.setattr(web,'_jobs',{'test':{'status':'running'}})
    web._run_incremental('test',web.CrawlAdvanceRequest(category='electric',year_min=1950,year_max=1980),'unused')
    assert web._jobs['test']['status']=='error'
    assert web._jobs['test']['error']=='Backup failure'


def test_non_guitar_batch_details_are_rejected():
    from ygc.crawl_service import _guitar_scope
    for kind in ['guitar','electric-bass-guitars','guitar-parts','amplifiers','pedals','']:
        assert not _guitar_scope({'product_type':kind})
    assert _guitar_scope({'product_type':'electric-guitars'})
    assert _guitar_scope({'product_type':'acoustic-guitars'})


def test_combined_crawl_creates_one_backup_before_both_searches(environment, monkeypatch):
    from test_incremental_crawl import CombinedCollector
    calls = []
    class FakeCollector(CombinedCollector):
        def __init__(self, **kwargs): super().__init__()
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def _get_json(self, url, params=None):
            if params: calls.append(params['query'])
            return super()._get_json(url, params)
    monkeypatch.setattr(web, 'ReverbAPICollector', FakeCollector)
    monkeypatch.setattr(crawl_backups, 'create', lambda export: calls.append('backup'))
    monkeypatch.setattr('ygc.incremental_crawl.MIN_REQUEST_GAP', 0)
    monkeypatch.setattr(web, '_jobs', {'test': {'status': 'running'}})
    web._run_incremental('test', web.CrawlAdvanceRequest(
        category='electric_acoustic', year_min=1970, year_max=1979), 'unused')
    assert calls == ['backup', 'electric guitar', 'acoustic guitar']
    assert web._jobs['test']['status'] == 'done'
    assert web._jobs['test']['aggregate']['new_individuals'] == 5


def test_unified_crawl_log_contains_manual_cached_backfill_and_old_runs(environment, monkeypatch):
    from test_crawl_service import Collector
    from ygc.crawl_service import crawl_query
    old = environment.start_run('reverb')
    environment.finish_run(old, pages_discovered=2, pages_fetched=1, status='ok')
    crawl_query(environment, Collector(), 'Fender', 10, year_min=1970, year_max=1979)
    monkeypatch.setattr(web, '_jobs', {'cache': {'status': 'running'}, 'backfill': {'status': 'running'}})
    web._run_cached_reprocess('cache', web.CrawlAdvanceRequest(category='electric_acoustic', year_min=1970, year_max=1979))
    monkeypatch.setattr(Repository, 'list_listing_claims_for_backfill', lambda self: [])
    web._run_metadata_backfill('backfill', 'unused')
    with TestClient(web.app) as client:
        response = client.get('/api/crawl/program/runs')
        assert response.status_code == 200
        runs = response.json()
        assert {r['category'] for r in runs} == {None, 'manual', 'cache_reprocess', 'metadata_backfill'}
        assert all(r['status'] == 'ok' for r in runs)
        assert next(r for r in runs if r['category'] == 'manual')['counts']['query'] == 'Fender'
        assert client.get('/api/crawl/program/runs?category=manual&year_min=1970&year_max=1979').status_code == 400


def test_failed_cached_reprocess_is_persisted(environment, monkeypatch):
    monkeypatch.setattr(web, '_jobs', {'cache': {'status': 'running'}})
    def fail(*args): raise OSError('Backup failed')
    monkeypatch.setattr(crawl_backups, 'create', fail)
    web._run_cached_reprocess('cache', web.CrawlAdvanceRequest(category='electric_acoustic', year_min=1970, year_max=1979))
    run = environment.crawl_run_log()[0]
    assert run['category'] == 'cache_reprocess' and run['status'] == 'error'
    assert run['error_message'] == 'Backup failed'


def test_manual_targets_and_independent_rotation(environment):
    from ygc import direct_queue
    with direct_queue.transaction() as con:
        con.execute("INSERT INTO settings VALUES ('example','original')")
    crawl_backups.configure('chronicle', generations=1)
    crawl_backups.configure('operations', generations=2)
    auth = crawl_backups.create(web.api_export_db, 'authentication', 'manual')
    ops = crawl_backups.create(web.api_export_db, 'operations', 'manual')
    first = crawl_backups.create(web.api_export_db, 'chronicle', 'manual')
    last = crawl_backups.create(web.api_export_db, 'chronicle', 'crawl')
    assert not (crawl_backups.directory()/first).exists()
    rows = crawl_backups.listing()
    assert {r['name'] for r in rows} == {auth, ops, last}
    assert {r['target'] for r in rows} == {'chronicle','operations','authentication'}
    assert next(r for r in rows if r['name'] == last)['reason'] == 'crawl'


def test_schedules_persist_reserve_once_and_record_failure(environment, monkeypatch):
    for target in crawl_backups.TARGETS:
        crawl_backups.configure(target, enabled=True, interval_hours=24)
    with operations.connect() as con:
        con.execute('UPDATE backup_schedules SET next_run=0')
    web._backup_tick()
    rows = crawl_backups.policies()
    assert all(r['next_run'] > 0 for r in rows)
    assert next(r for r in rows if r['target']=='authentication')['last_status']=='error'
    assert next(r for r in rows if r['target']=='chronicle')['last_status']=='ok'
    assert next(r for r in rows if r['target']=='operations')['last_status']=='ok'
    count = len(crawl_backups.listing())
    web._backup_tick()
    assert len(crawl_backups.listing()) == count
    assert all(r['enabled'] for r in crawl_backups.policies())
    monkeypatch.setattr(web, '_jobs', {'busy': {'status':'running'}})
    with operations.connect() as con:
        con.execute('UPDATE backup_schedules SET next_run=0')
    web._backup_tick()
    assert all(r['next_run']==0 for r in crawl_backups.policies())


def test_operations_restore_preserves_maintenance_schedule_and_other_databases(environment):
    environment.create_user('Unchanged')
    operations.update('normal','old message','test',operations.state()['version'])
    operations.set_auto_crawl(True,'electric_acoustic',1950,1980,3600)
    operations.chatgpt_review(True)
    name = crawl_backups.create(web.api_export_db,'operations','manual')
    crawl_backups.configure('operations', enabled=True, generations=20, interval_hours=12)
    operations.update('read_only','Current maintenance','test',operations.state()['version'])
    with TestClient(web.app, base_url='http://127.0.0.1', client=('127.0.0.1',45000)) as client:
        url='/api/admin/operations/backups/'+name+'/restore'
        assert client.post(url).status_code==403
        response=client.post(url,headers=ADMIN)
        assert response.status_code==200,response.text
    assert operations.state()['mode']=='read_only'
    assert operations.state()['message']=='Current maintenance'
    assert operations.auto_crawl()['enabled']==0
    assert operations.chatgpt_review()['enabled']==0
    policy = next(r for r in crawl_backups.policies() if r['target']=='operations')
    assert (policy['enabled'],policy['generations'],policy['interval_hours'])==(1,20,12)
    assert [r['display_name'] for r in environment.list_users()]==['Unchanged']
    assert any(r['reason']=='before_restore' and r['target']=='operations' for r in crawl_backups.listing())


def test_authentication_restore_from_file_is_targeted_and_revokes_token(environment):
    from ygc import direct_queue
    environment.create_user('Unchanged')
    with direct_queue.transaction() as con:
        con.execute("INSERT INTO settings VALUES ('example','original')")
        direct_queue.token(con, create=True)
    name=crawl_backups.create(web.api_export_db,'authentication','manual')
    payload=crawl_backups.selected(name).read_bytes()
    with direct_queue.transaction() as con:
        con.execute("UPDATE settings SET value='later' WHERE name='example'")
    with TestClient(web.app, base_url='http://127.0.0.1', client=('127.0.0.1',45000)) as client:
        url='/api/admin/operations/backups/import?target=authentication'
        assert client.post(url,headers=ADMIN,content=payload).status_code==409
        operations.update('offline','','test',operations.state()['version'])
        assert client.post(url,headers=ADMIN,content=payload).status_code==200
        assert client.post('/api/admin/operations/backups/import?target=operations',headers=ADMIN,content=payload).status_code==400
    with direct_queue.transaction() as con:
        assert con.execute("SELECT value FROM settings WHERE name='example'").fetchone()[0]=='original'
        assert direct_queue.token(con) is None
    assert [r['display_name'] for r in environment.list_users()]==['Unchanged']
    assert operations.state()['mode']=='offline'


def test_backup_endpoints_save_download_authorization(environment):
    with TestClient(web.app, base_url='http://127.0.0.1', client=('127.0.0.1',45000)) as client:
        assert client.post('/api/admin/operations/backups/save',json={'target':'chronicle'}).status_code==403
        response=client.post('/api/admin/operations/backups/save',headers=ADMIN,json={'target':'chronicle'})
        assert response.status_code==200,response.text
        name=response.json()['name']
        assert client.get('/api/admin/operations/backups/'+name+'/download').status_code==403
        response=client.get('/api/admin/operations/backups/'+name+'/download',headers=ADMIN)
        assert response.status_code==200 and response.content[:2]==b'PK'
        assert client.get('/api/admin/operations/backups/../outside/download',headers=ADMIN).status_code==404
