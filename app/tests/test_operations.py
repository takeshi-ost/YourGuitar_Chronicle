import sqlite3

import pytest
from fastapi.testclient import TestClient
from ygc import config, operations
from ygc.web import app, CONSOLE_ADMIN_TOKEN


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'chronicle.db')
    with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 45000)) as c:
        yield c


ADMIN = {'X-YGC-Console-Admin': CONSOLE_ADMIN_TOKEN}


def save(client, mode, version=0, message='Maintenance'):
    return client.put('/api/admin/operations', headers=ADMIN, json={
        'mode': mode, 'message': message, 'reason': 'Scheduled maintenance', 'expected_version': version})


def test_admin_only_settings_and_status(client):
    assert client.get('/api/admin/operations').status_code == 403
    assert client.put('/api/admin/operations', json={
        'mode':'offline','reason':'test','expected_version':0}).status_code == 403
    data = client.get('/api/admin/operations', headers=ADMIN).json()
    assert data['database'] == 'available'
    assert data['settings']['mode'] == 'normal'
    assert 'CONSOLE_ADMIN_TOKEN' not in str(data)


def test_read_only_blocks_all_writes_including_admin_but_allows_recovery(client):
    assert save(client, 'read_only').status_code == 200
    assert client.get('/api/individuals').status_code == 200
    assert client.post('/api/users', json={'display_name':'Blocked'}).status_code == 503
    assert client.post('/api/reset-db', headers=ADMIN).status_code == 503
    assert client.post('/api/experiments/direct/mcp').status_code == 503
    assert client.get('/health/ready').status_code == 200
    assert save(client, 'normal', 1).status_code == 200
    assert client.get('/api/admin/operations', headers=ADMIN).json()['settings']['version'] == 2


def test_offline_page_escaping_health_and_persistence(client):
    assert save(client, 'offline', message='<script>alert(1)</script>').status_code == 200
    assert client.get('/api/individuals').status_code == 503
    response=client.get('/user-view')
    assert response.status_code == 503
    assert '<script>' not in response.text
    assert response.headers['retry-after'] == '60'
    assert client.get('/').status_code == 200
    assert client.get('/assets/pages/console.js').status_code == 200
    assert client.get('/health/live').status_code == 200
    assert client.get('/health/ready').status_code == 503
    assert operations.state()['mode'] == 'offline'
    assert len(operations.history()) == 1
    assert save(client, 'normal', 1).status_code == 200


def test_conflicting_save_and_optional_reason(client):
    assert save(client, 'read_only').status_code == 200
    assert save(client, 'offline').status_code == 409
    assert operations.state()['mode'] == 'read_only'
    assert client.put('/api/admin/operations', headers=ADMIN,json={
        'mode':'normal','expected_version':1}).status_code == 200


def test_ready_does_not_create_missing_database(client):
    config.DB_PATH.unlink()
    assert client.get('/health/ready').status_code == 503
    assert not config.DB_PATH.exists()


def test_auto_crawl_toggle_and_worker(client, monkeypatch):
    import time
    from ygc import web
    monkeypatch.setattr(web,'_AUTO_CRAWL_TOKEN','')
    monkeypatch.setattr(web,'_active_job_id',None)
    monkeypatch.setattr(web,'_jobs',{})
    body={'enabled':True,'category':'electric','year_min':1950,'year_max':1980,'interval_seconds':3600}
    assert client.put('/api/admin/operations/auto-crawl',json=body).status_code==403
    assert client.put('/api/admin/operations/auto-crawl',headers=ADMIN,json=body).status_code==400
    headers={**ADMIN,'X-Reverb-Token':'test-only-token'}
    assert client.put('/api/admin/operations/auto-crawl',headers=headers,json=body).status_code==200
    assert operations.auto_crawl()['enabled']==1
    assert 'test-only-token' not in str(client.get('/api/admin/operations',headers=ADMIN).json())
    with operations.connect() as con:
        con.execute('UPDATE auto_crawl SET next_run=0')
    class Ready:
        def claim_architecture_status(self):return {'ready':True}
    monkeypatch.setattr(web,'repo',lambda:Ready())
    launched=[]
    class FakeThread:
        def __init__(self,**kwargs):launched.append(kwargs)
        def start(self):pass
    monkeypatch.setattr(web.threading,'Thread',FakeThread)
    web._auto_crawl_tick()
    assert len(launched)==1
    assert launched[0]['args'][1].category=='electric_acoustic'
    web._auto_crawl_tick()
    assert len(launched)==1
    body['enabled']=False
    assert client.put('/api/admin/operations/auto-crawl',headers=ADMIN,json=body).status_code==200
    assert operations.auto_crawl()['enabled']==0


def test_auto_crawl_maintenance_and_reservation(client):
    assert operations.auto_crawl()['enabled']==0
    operations.set_auto_crawl(True,'electric',1950,1980,3600)
    assert not operations.reserve_auto_crawl(0)
    with operations.connect() as con:con.execute('UPDATE auto_crawl SET next_run=0')
    assert operations.reserve_auto_crawl(10)
    assert not operations.reserve_auto_crawl(10)
    assert save(client,'read_only').status_code==200
    assert client.put('/api/admin/operations/auto-crawl',headers=ADMIN,json={
        'enabled':False,'category':'electric','year_min':1950,'year_max':1980}).status_code==200


def test_chatgpt_review_switch_persists_and_pauses_both_queues(client):
    from ygc import acquire_review
    from ygc.db.repository import Repository
    assert operations.chatgpt_review()['enabled']
    assert client.put('/api/admin/operations/chatgpt-review',json={'enabled':False}).status_code==403
    assert client.put('/api/admin/operations/chatgpt-review',headers=ADMIN,json={'enabled':False}).status_code==200
    assert not operations.chatgpt_review()['enabled']
    for tool in ['ygc_pending_acquire','ygc_pending_listing']:
        result=acquire_review.call_tool(Repository(config.DB_PATH),tool,{})
        assert result['jobs']==[]
        assert 'paused' in result['instructions']
    status=client.get('/api/admin/operations',headers=ADMIN).json()
    assert status['last_gpt_answer_at'] is None
    assert client.put('/api/admin/operations/chatgpt-review',headers=ADMIN,json={'enabled':True}).status_code==200


def test_old_auto_crawl_scope_migrates_without_changing_schedule(client):
    operations.auto_crawl()
    with operations.connect() as con:
        con.execute("UPDATE auto_crawl SET enabled=1,category='acoustic',year_min=1960,year_max=1990,interval_seconds=7200,next_run=12345")
    settings = operations.auto_crawl()
    assert settings['category'] == 'electric_acoustic'
    assert (settings['enabled'], settings['year_min'], settings['year_max'], settings['interval_seconds'], settings['next_run']) == (1, 1960, 1990, 7200, 12345)
