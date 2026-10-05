from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_self_guitars_routes import self_guitars_router
from ygc.identity_platform import VerifiedIdentity


@pytest.fixture
def api():
    verifier=Mock();verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True)
    verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical-member','role':'member'}
    service=Mock();service.own_guitars.return_value=dict(total=0,items=[],next_after=None)
    app=FastAPI();app.include_router(self_guitars_router(verifier,service))
    with TestClient(app) as client:yield client,verifier,service

AUTH={'Authorization':'Bearer token'}


def test_canonical_self_and_bigint_precision(api):
    client,_,service=api;value=2**63-1
    service.own_guitars.return_value=dict(total=value,items=[dict(id=value,model='Model')],next_after=value)
    response=client.get('/api/auth/guitars?kind=formerly_owned&after=2&limit=10',headers=AUTH)
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    assert response.json()==dict(total=str(value),items=[dict(id=str(value),model='Model')],next_after=str(value))
    service.own_guitars.assert_called_once_with('canonical-member',kind='formerly_owned',after=2,limit=10)


@pytest.mark.parametrize('query',['user_id=2','q=other','kind=other','kind=owned&kind=formerly_owned','limit=51','after=0','limit=-1'])
def test_no_target_selection_or_invalid_page(api,query):
    client,_,service=api
    assert client.get('/api/auth/guitars?'+query,headers=AUTH).status_code==400
    service.own_guitars.assert_not_called()


@pytest.mark.parametrize('case,status',[('missing',401),('token',401),('email',403),('disabled',403),('outage',503),('mode',403)])
def test_refusal_before_content(api,case,status):
    client,verifier,service=api;headers=AUTH
    if case=='missing':headers={}
    if case=='token':verifier.verify.side_effect=PermissionError('secret')
    if case=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if case=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError('secret')
    if case=='outage':verifier.verify.side_effect=RuntimeError('secret')
    if case=='mode':service.own_guitars.side_effect=PermissionError('secret')
    response=client.get('/api/auth/guitars',headers=headers)
    assert response.status_code==status and 'secret' not in response.text
    if case!='mode':service.own_guitars.assert_not_called()


def test_default_page_and_no_write_routes(api):
    client,_,service=api
    assert client.get('/api/auth/guitars',headers=AUTH).json()==dict(total='0',items=[],next_after=None)
    service.own_guitars.assert_called_once_with('canonical-member',kind='owned',after=0,limit=25)
    for method in ('post','put','delete'):
        assert getattr(client,method)('/api/auth/guitars',headers=AUTH).status_code==405
