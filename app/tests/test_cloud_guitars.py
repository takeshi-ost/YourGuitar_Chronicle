from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import QueryParams
from ygc.cloud_guitars import parameters,positive_id,GuitarMissing
from ygc.cloud_guitar_routes import guitar_router
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
    service=Mock();service.list.return_value={'total':0,'items':[],'next_after':None};service.detail.return_value={'id':1,'manufacturer':'Maker'}
    app=FastAPI();app.include_router(guitar_router(verifier,service))
    with TestClient(app) as client:yield client,verifier,service


AUTH={'Authorization':'Bearer token'}


def test_canonical_actor_no_store_and_no_mutations(api):
    client,verifier,service=api
    result=client.get('/api/admin/guitars?q=maker&after=2&limit=10',headers=AUTH)
    assert result.status_code==200 and result.headers['cache-control']=='private, no-store'
    service.list.assert_called_once_with('canonical',q='maker',after=2,limit=10)
    assert client.get('/api/admin/guitars/1',headers=AUTH).status_code==200
    service.detail.assert_called_once_with('canonical',1)
    for method in ('put','post','delete'):
        assert getattr(client,method)('/api/admin/guitars/1',headers=AUTH).status_code==405


@pytest.mark.parametrize('case,status',[('missing',401),('token',401),('email',403),('member',403),('disabled',403),('identity_error',503)])
def test_reject_before_read(api,case,status):
    client,verifier,service=api;headers=AUTH
    if case=='missing':headers={}
    if case=='token':verifier.verify.side_effect=PermissionError('private')
    if case=='identity_error':verifier.verify.side_effect=RuntimeError('private')
    if case=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if case=='member':verifier.accounts.resolve_identity.return_value['role']='member'
    if case=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError('private')
    result=client.get('/api/admin/guitars',headers=headers)
    assert result.status_code==status and 'private' not in result.text
    service.list.assert_not_called()


@pytest.mark.parametrize('error,status',[(GuitarMissing(),404),(PermissionError('private'),403),(RuntimeError('private'),503)])
def test_failures_private(api,error,status):
    client,verifier,service=api;service.detail.side_effect=error
    result=client.get('/api/admin/guitars/1',headers=AUTH)
    assert result.status_code==status and 'private' not in result.text


def test_invalid_params_never_execute(api):
    client,verifier,service=api
    for path in ('/api/admin/guitars?role=admin','/api/admin/guitars/0','/api/admin/guitars/1?viewer_id=2'):
        assert client.get(path,headers=AUTH).status_code==400
    service.list.assert_not_called();service.detail.assert_not_called()


def test_bigint_response_preserves_decimal_precision(api):
    client,verifier,service=api
    value=2**63-1
    service.detail.return_value={'id':value,'manufacturer':'Maker'}
    assert client.get('/api/admin/guitars/'+str(value),headers=AUTH).json()['id']==str(value)
    service.list.return_value={'total':value,'items':[{'id':value}], 'next_after':value}
    result=client.get('/api/admin/guitars',headers=AUTH).json()
    assert result['items'][0]['id']==result['next_after']==str(value)
    assert result['total']==str(value)
    assert service.list.return_value['items'][0]['id']==value


def test_chronicle_uses_canonical_admin_and_precision(api):
    client,verifier,service=api;value=2**63-1
    service.chronicle.return_value=dict(items=[dict(id=value,author_user_id=value,claim_type='listing')],total=value,next_after=value)
    response=client.get('/api/admin/guitars/1/chronicle?after=5&limit=10',headers=AUTH)
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    assert response.json()['items'][0]['author_user_id']==str(value)
    assert response.json()['total']==response.json()['next_after']==str(value)
    service.chronicle.assert_called_once_with('canonical',1,after=5,limit=10)


@pytest.mark.parametrize('failure,status',[('missing',401),('email',403),('member',403),('disabled',403)])
def test_chronicle_rejects_before_history_read(api,failure,status):
    client,verifier,service=api;headers=AUTH
    if failure=='missing':headers={}
    if failure=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if failure=='member':verifier.accounts.resolve_identity.return_value['role']='member'
    if failure=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError()
    assert client.get('/api/admin/guitars/1/chronicle',headers=headers).status_code==status
    service.chronicle.assert_not_called()


def test_chronicle_has_no_mutation_routes_and_strict_parameters(api):
    client,verifier,service=api
    for query in ['q=name','after=0','viewer_id=1','limit=51','after=1&after=2']:
        assert client.get('/api/admin/guitars/1/chronicle?'+query,headers=AUTH).status_code==400
    for method in ['post','put','delete']:
        assert getattr(client,method)('/api/admin/guitars/1/chronicle',headers=AUTH).status_code==405
    service.chronicle.assert_not_called()


def test_admin_decision_uses_canonical_actor(api):
    client,verifier,service=api
    service.moderate.return_value=dict(claim_id='2',individual_id='1',verification_status='negative')
    response=client.post('/api/admin/guitars/1/claims/2/verification',headers=AUTH,json=dict(action='negative',revision='a'*64))
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    service.moderate.assert_called_once_with('canonical',1,2,action='negative',revision='a'*64)


@pytest.mark.parametrize('payload',[{},[],dict(action='positive',revision='a'*64,actor='injected')])
def test_invalid_decision_payload_never_executes(api,payload):
    client,verifier,service=api
    assert client.post('/api/admin/guitars/1/claims/2/verification',headers=AUTH,json=payload).status_code==400
    service.moderate.assert_not_called()


def test_duplicate_decision_keys_and_large_payload(api):
    client,verifier,service=api
    for raw in ('{"action":"positive","action":"negative","revision":"x"}','x'*1025):
        assert client.post('/api/admin/guitars/1/claims/2/verification',headers=AUTH|{'Content-Type':'application/json'},content=raw).status_code==400
    service.moderate.assert_not_called()


@pytest.mark.parametrize('failure,status',[('missing',401),('email',403),('member',403),('disabled',403)])
def test_decision_auth_rejected_before_write(api,failure,status):
    client,verifier,service=api;headers=AUTH
    if failure=='missing':headers={}
    if failure=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if failure=='member':verifier.accounts.resolve_identity.return_value['role']='member'
    if failure=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError('private')
    assert client.post('/api/admin/guitars/1/claims/2/verification',headers=headers,json=dict(action='positive',revision='a'*64)).status_code==status
    service.moderate.assert_not_called()


def test_decision_conflict_and_errors_private(api):
    from ygc.claim_revision import ClaimConflict
    client,verifier,service=api
    for error,status in [(ClaimConflict('private'),409),(ValueError('private'),400),(PermissionError('private'),403),(RuntimeError('private'),503)]:
        service.moderate.side_effect=error
        result=client.post('/api/admin/guitars/1/claims/2/verification',headers=AUTH,json=dict(action='positive',revision='a'*64))
        assert result.status_code==status and 'private' not in result.text


@pytest.mark.parametrize('action,revision',[('delete','a'*64),('invalid','a'*64),('positive','x'),('positive',None)])
def test_service_invalid_decision_no_database(action,revision):
    from ygc.cloud_guitars import CloudGuitars
    service=CloudGuitars(None,None)
    with pytest.raises(ValueError):service.moderate('actor',1,2,action=action,revision=revision)
