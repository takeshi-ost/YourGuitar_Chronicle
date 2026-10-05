from unittest.mock import Mock
from datetime import datetime,timezone,timedelta
import uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_crawl_control import CrawlJobClient,validate,public
from ygc.cloud_crawl_routes import crawl_router
from ygc.identity_platform import VerifiedIdentity


@pytest.mark.parametrize('values',[(1799,1980,1),(1950,2101,1),(1980,1950,1),(True,1980,1),(1950,1980,0),(1950,1980,169),(1950,1980,True)])
def test_settings_strict_bounds(values):
    with pytest.raises(ValueError):validate(*values)


def test_fixed_job_uuid_only_overrides_and_unexpected_target_rejected():
    session=Mock();session.post.return_value.json.return_value={'name':'projects/project/locations/asia-northeast1/operations/operation'}
    client=CrawlJobClient('project','asia-northeast1',session=session);token=str(uuid.uuid4())
    client.start('chronicle',token)
    args=session.post.call_args.kwargs['json']['overrides']['containerOverrides'][0]['args']
    assert args==['-m','ygc.cloud_crawl_job','--confirm-project=project','--request-id='+token]
    with pytest.raises(ValueError):client.start('accounts',token)


def test_public_status_never_returns_secret_provider_resource_or_counts():
    result=public(dict(request_id='id',state='running',created_at=(datetime.now(timezone.utc)-timedelta(minutes=31)).isoformat(),source='manual',year_min=1950,year_max=1980,operation='private',actor='private',counts={'private':'value'}))
    assert result['retry_allowed'] and result['state']=='unknown' and not {'actor','counts','operation'}&set(result)


@pytest.mark.parametrize('failure,status',[('missing',401),('email',403),('member',403),('disabled',403),('provider',503)])
def test_crawl_api_requires_verified_live_admin(failure,status):
    verifier=Mock();control=Mock();verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True)
    verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical','role':'admin'}
    auth={'Authorization':'Bearer token'}
    if failure=='missing':auth={}
    if failure=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if failure=='member':verifier.accounts.resolve_identity.return_value['role']='member'
    if failure=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError()
    if failure=='provider':verifier.verify.side_effect=RuntimeError('private')
    app=FastAPI();app.include_router(crawl_router(verifier,control))
    with TestClient(app) as client:
        assert client.get('/api/admin/crawl',headers=auth).status_code==status
        assert client.post('/api/admin/crawl/start',json={},headers=auth).status_code==status
    control.details.assert_not_called();control.start.assert_not_called()


def test_rollout_refuses_missing_user_secret_before_iam_mutations(monkeypatch):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    path=Path(__file__).resolve().parents[2]/'scripts/deploy_cloud_crawl.py'
    spec=importlib.util.spec_from_file_location('deploy_cloud_crawl',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1,stdout='',stderr='NOT_FOUND')
    monkeypatch.setattr(module.subprocess,'run',run)
    monkeypatch.setattr('sys.argv',['deploy_cloud_crawl.py','--project','your-guitar-chronicle-staging','--region','asia-northeast1','--image','asia-northeast1-docker.pkg.dev/your-guitar-chronicle-staging/ygc-staging/account-api@sha256:'+'0'*64])
    with pytest.raises(RuntimeError):module.main()
    assert len(calls)==1 and calls[0][1:4]==['secrets','versions','describe']
    assert 'get-secret-value' not in calls[0] and 'access' not in calls[0]


def test_rollout_creates_job_for_gcloud_cannot_find_response(monkeypatch):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    path=Path(__file__).resolve().parents[2]/'scripts/deploy_cloud_crawl.py'
    spec=importlib.util.spec_from_file_location('deploy_cloud_crawl_create',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        parts=command[1:]
        if parts[:3]==['secrets','versions','describe']:return SimpleNamespace(returncode=0,stdout='ENABLED',stderr='')
        if parts[:3]==['iam','roles','describe']:return SimpleNamespace(returncode=0,stdout='{"includedPermissions":["run.jobs.run","run.jobs.runWithOverrides","run.executions.get"]}',stderr='')
        if parts[:3]==['run','jobs','describe']:return SimpleNamespace(returncode=1,stdout='',stderr='ERROR: Cannot find job [ygc-staging-reverb-crawl].')
        if parts[:3]==['scheduler','jobs','describe']:return SimpleNamespace(returncode=1,stdout='',stderr='NOT_FOUND')
        return SimpleNamespace(returncode=0,stdout='configured',stderr='')
    monkeypatch.setattr(module.subprocess,'run',run)
    monkeypatch.setattr('sys.argv',['deploy_cloud_crawl.py','--project','your-guitar-chronicle-staging','--region','asia-northeast1','--image','asia-northeast1-docker.pkg.dev/your-guitar-chronicle-staging/ygc-staging/account-api@sha256:'+'0'*64])
    module.main()
    assert any(command[1:4]==['run','jobs','create'] for command in calls)
    assert any(command[1:4]==['scheduler','jobs','create'] for command in calls)
    assert not any(command[1:4]==['run','jobs','execute'] for command in calls)


@pytest.mark.parametrize('value',[0,2001,-1,True,1.5,'3',None])
def test_crawl_limit_requires_integer_in_range(value):
    from ygc.cloud_crawl_job import validate_limit
    with pytest.raises(ValueError):validate_limit(value)


def test_old_settings_have_two_thousand_default():
    from ygc.cloud_crawl_job import configured_limit
    con=Mock();con.execute.return_value.fetchone.return_value=None
    assert configured_limit(con)==2000
    con.execute.return_value.fetchone.return_value={'reason':'{"action":"crawl_settings","enabled":false}'}
    assert configured_limit(con)==2000
