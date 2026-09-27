from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from ygc import config
from ygc.db.repository import Repository
from ygc.platform_boundaries import (
    ActorContext, CrawlStep, LocalCrawlRunner, PlatformAdapterRequired,
    PrototypeIdentity, local_repository, require_local_platform,
)
from ygc.web import app


def test_prototype_identity_is_never_verified():
    actor = PrototypeIdentity().resolve(prototype_user_id=42)
    assert actor == ActorContext(42, 'prototype', None, False)
    with pytest.raises(PlatformAdapterRequired, match='verifier'):
        PrototypeIdentity().resolve(bearer_token='unverified', prototype_user_id=42)


@pytest.mark.parametrize('key,value', [
    ('YGC_PLATFORM_TARGET','cloud_run'),
    ('YGC_IDENTITY_BACKEND','identity_platform'),
    ('YGC_DATABASE_BACKEND','postgresql'),
    ('YGC_CRAWL_BACKEND','cloud_run_jobs'),
    ('YGC_MEDIA_BACKEND','cloud_storage'),
    ('K_SERVICE','production-service'),
    ('CLOUD_RUN_JOB','production-job'),
])
def test_cloud_selection_never_falls_back_to_local(tmp_path,monkeypatch,key,value):
    monkeypatch.setenv(key,value)
    with pytest.raises(PlatformAdapterRequired):
        local_repository(tmp_path/'must-not-be-created.db')
    assert not (tmp_path/'must-not-be-created.db').exists()


def test_identity_mapping_is_nullable_and_unique_after_migration(tmp_path):
    repo=Repository(tmp_path/'users.db');repo.init_db()
    alice=repo.create_user('Alice')
    bob=repo.create_user('Bob')
    assert repo.get_user(alice)[0]['identity_subject'] is None
    with repo.connect() as con:
        con.execute("UPDATE users SET identity_provider='identity_platform',identity_subject='uid-1' WHERE id=?",(alice,))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE users SET identity_provider='identity_platform',identity_subject='uid-1' WHERE id=?",(bob,))
    repo.init_db()


def test_synchronous_crawl_step_uses_existing_cursor_and_log(tmp_path):
    class EmptyCollector:
        api_base='https://example.test'
        def _get_json(self,url,params=None):
            return {'listings':[]}
        def _next_href(self,payload):
            return None
    repo=Repository(tmp_path/'crawl.db');repo.init_db()
    step=CrawlStep('electric',1950,1980)
    result=LocalCrawlRunner().run(step,repo,EmptyCollector())
    assert result['summaries_processed']==0
    assert result['finished']
    assert repo.crawl_run_log('electric',1950,1980)[0]['status']=='ok'
    with pytest.raises(ValueError):
        CrawlStep('electric',1980,1950)


def test_viewer_endpoint_keeps_prototype_contract_explicit(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'web.db')
    with TestClient(app) as client:
        response=client.get('/api/users/999/profile?viewer_id=1',headers={'Authorization':'Bearer fake'})
        assert response.status_code==401
        assert 'verifier' in response.json()['detail']
