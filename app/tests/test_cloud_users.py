from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import QueryParams
from ygc.cloud_users import parameters,positive_id,UserMissing
from ygc.cloud_user_routes import user_router
from ygc.identity_platform import VerifiedIdentity


@pytest.mark.parametrize('value',['0','-1','1.0','١','1 OR 1=1',str(2**63),''])
def test_invalid_id(value):
    with pytest.raises(ValueError):positive_id(value)


@pytest.mark.parametrize('query',['limit=51','limit=0','after=-1','viewer_id=1','q=a&q=b','q='+('x'*121),'q=%00'])
def test_invalid_query(query):
    with pytest.raises(ValueError):parameters(QueryParams(query))


def test_query_defaults_and_literals():
    assert parameters(QueryParams())==('',0,25)
    assert parameters(QueryParams('q=%25_&after=3&limit=50'))==('%_',3,50)


@pytest.fixture
def api():
    verifier=Mock();verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True)
    verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical','role':'admin'}
    service=Mock();service.list.return_value={'total':0,'items':[],'next_after':None};service.detail.return_value={'id':1,'display_name':'Member'}
    app=FastAPI();app.include_router(user_router(verifier,service))
    with TestClient(app) as client:yield client,verifier,service


AUTH={'Authorization':'Bearer token'}


def test_canonical_actor_no_store_and_no_mutations(api):
    client,verifier,service=api
    result=client.get('/api/admin/users?q=maker&after=2&limit=10',headers=AUTH)
    assert result.status_code==200 and result.headers['cache-control']=='private, no-store'
    service.list.assert_called_once_with('canonical',q='maker',after=2,limit=10)
    assert client.get('/api/admin/users/1',headers=AUTH).status_code==200
    service.detail.assert_called_once_with('canonical',1)
    for method in ('put','post','delete'):
        assert getattr(client,method)('/api/admin/users/1',headers=AUTH).status_code==405


@pytest.mark.parametrize('case,status',[('missing',401),('token',401),('email',403),('member',403),('disabled',403),('identity_error',503)])
def test_reject_before_read(api,case,status):
    client,verifier,service=api;headers=AUTH
    if case=='missing':headers={}
    if case=='token':verifier.verify.side_effect=PermissionError('private')
    if case=='identity_error':verifier.verify.side_effect=RuntimeError('private')
    if case=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if case=='member':verifier.accounts.resolve_identity.return_value['role']='member'
    if case=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError('private')
    result=client.get('/api/admin/users',headers=headers)
    assert result.status_code==status and 'private' not in result.text
    service.list.assert_not_called()


@pytest.mark.parametrize('error,status',[(UserMissing(),404),(PermissionError('private'),403),(RuntimeError('private'),503)])
def test_failures_private(api,error,status):
    client,verifier,service=api;service.detail.side_effect=error
    result=client.get('/api/admin/users/1',headers=AUTH)
    assert result.status_code==status and 'private' not in result.text


def test_invalid_params_never_execute(api):
    client,verifier,service=api
    for path in ('/api/admin/users?role=admin','/api/admin/users/0','/api/admin/users/1?viewer_id=2'):
        assert client.get(path,headers=AUTH).status_code==400
    service.list.assert_not_called();service.detail.assert_not_called()


def test_bigint_response_preserves_decimal_precision(api):
    client,verifier,service=api
    value=2**63-1
    service.detail.return_value={'id':value,'display_name':'Member'}
    assert client.get('/api/admin/users/'+str(value),headers=AUTH).json()['id']==str(value)
    service.list.return_value={'total':value,'items':[{'id':value}], 'next_after':value}
    result=client.get('/api/admin/users',headers=AUTH).json()
    assert result['items'][0]['id']==result['next_after']==str(value)
    assert result['total']==str(value)
    assert service.list.return_value['items'][0]['id']==value


def test_owned_page_canonical_admin_and_precision(api):
    client,verifier,service=api;value=2**63-1
    service.guitars.return_value=dict(items=[dict(id=value,manufacturer='Maker')],total=value,next_after=value)
    response=client.get('/api/admin/users/1/guitars?kind=formerly_owned&after=2&limit=10',headers=AUTH)
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    assert response.json()['total']==response.json()['items'][0]['id']==response.json()['next_after']==str(value)
    service.guitars.assert_called_once_with('canonical',1,kind='formerly_owned',after=2,limit=10)


@pytest.mark.parametrize('query',['kind=pending','kind=owned&kind=owned','q=abc','viewer_id=2','limit=51','after=0'])
def test_owned_page_invalid_query_never_reads(api,query):
    client,verifier,service=api
    assert client.get('/api/admin/users/1/guitars?'+query,headers=AUTH).status_code==400
    service.guitars.assert_not_called()


@pytest.mark.parametrize('case,status',[('missing',401),('email',403),('member',403),('disabled',403)])
def test_owned_page_identity_rejected_before_read(api,case,status):
    client,verifier,service=api;headers=AUTH
    if case=='missing':headers={}
    if case=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if case=='member':verifier.accounts.resolve_identity.return_value['role']='member'
    if case=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError()
    assert client.get('/api/admin/users/1/guitars',headers=headers).status_code==status
    service.guitars.assert_not_called()


def test_owned_page_failures_private(api):
    client,verifier,service=api
    for failure,status in [(UserMissing(),404),(PermissionError('private'),403),(RuntimeError('private'),503)]:
        service.guitars.side_effect=failure
        response=client.get('/api/admin/users/1/guitars',headers=AUTH)
        assert response.status_code==status and 'private' not in response.text
