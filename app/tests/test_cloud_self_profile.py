from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_self_profile_routes import self_profile_router
from ygc.cloud_profile import ProfileConflict
from ygc.identity_platform import VerifiedIdentity
from test_cloud_profile import BODY


@pytest.fixture
def api():
    verifier=Mock();verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True)
    verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical-member','role':'member'}
    service=Mock();service.own_profile.return_value=BODY;service.edit_own_profile.return_value={'saved':True}
    app=FastAPI();app.include_router(self_profile_router(verifier,service))
    with TestClient(app) as client:yield client,verifier,service

AUTH={'Authorization':'Bearer token'}


def test_self_actor_private_response(api):
    client,verifier,service=api
    result=client.get('/api/auth/profile',headers=AUTH)
    assert result.status_code==200 and result.headers['cache-control']=='private, no-store'
    service.own_profile.assert_called_once_with('canonical-member')
    assert client.put('/api/auth/profile',headers=AUTH,json=BODY).status_code==200
    service.edit_own_profile.assert_called_once_with('canonical-member',BODY)


@pytest.mark.parametrize('case,status',[('missing',401),('token',401),('email',403),('disabled',403),('unavailable',503)])
def test_identity_rejection(api,case,status):
    client,verifier,service=api;headers=AUTH
    if case=='missing':headers={}
    if case=='token':verifier.verify.side_effect=PermissionError('secret')
    if case=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if case=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError('secret')
    if case=='unavailable':verifier.verify.side_effect=RuntimeError('secret')
    for method in ('get','put'):
        response=getattr(client,method)('/api/auth/profile',headers=headers)
        assert response.status_code==status and 'secret' not in response.text
    service.own_profile.assert_not_called();service.edit_own_profile.assert_not_called()


@pytest.mark.parametrize('body',['{"revision":"1","revision":"2","fields":{}}','{"revision":"1","fields":{"role":"admin"}}','[]'])
def test_invalid_body(api,body):
    client,_,service=api
    assert client.put('/api/auth/profile',headers={**AUTH,'Content-Type':'application/json'},content=body).status_code==400
    service.edit_own_profile.assert_not_called()


def test_target_and_size_rejected(api):
    client,_,service=api
    assert client.get('/api/auth/profile?user_id=2',headers=AUTH).status_code==400
    assert client.put('/api/auth/profile?user_id=2',headers=AUTH,json=BODY).status_code==400
    assert client.put('/api/auth/profile',headers={**AUTH,'Content-Type':'application/json'},content=' '*20001).status_code==413
    assert client.put('/api/auth/profile',headers=AUTH,content='{}').status_code==400
    service.own_profile.assert_not_called();service.edit_own_profile.assert_not_called()


@pytest.mark.parametrize('error,status',[(ProfileConflict('secret'),409),(PermissionError('secret'),403),(RuntimeError('secret'),503)])
def test_save_failures_no_leak(api,error,status):
    client,_,service=api;service.edit_own_profile.side_effect=error
    response=client.put('/api/auth/profile',headers=AUTH,json=BODY)
    assert response.status_code==status and 'secret' not in response.text
