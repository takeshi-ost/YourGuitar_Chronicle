from unittest.mock import Mock
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_application_routes import application_router
from ygc.cloud_applications import listing_input, revision_id, verify_restored_applications
from ygc.cloud_content_media import encode_reference
from ygc.identity_platform import VerifiedIdentity
from test_cloud_avatar import Storage, png

REV='a'*32
AUTH={'Authorization':'Bearer token'}
BASE='/api/auth/applications'


@pytest.fixture
def api():
    verifier=Mock();verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True)
    verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical','role':'member'}
    service=Mock();service.list.return_value={'items':[]};service.start.return_value={'revision':REV,'status':'draft'}
    service.upload.return_value={'revision':REV,'photos':['closeup']};service.submit.return_value={'status':'pending'};service.cancel.return_value={'status':'cancelled'};service.image.return_value=b'jpeg'
    app=FastAPI();app.include_router(application_router(verifier,service))
    with TestClient(app) as client:yield client,verifier,service


def test_applicant_bound_api_and_private_photos(api):
    client,verifier,service=api
    assert client.get(BASE,headers=AUTH).json()=={'items':[]}
    body={'kind':'acquire','individual_id':'12'}
    response=client.post(BASE,headers=AUTH,json=body)
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    service.start.assert_called_once_with('canonical',body)
    path=BASE+'/'+REV
    assert client.post(path+'/photos/closeup',headers=AUTH|{'Content-Type':'image/png'},content=png()).status_code==200
    service.upload.assert_called_once_with('canonical',REV,'closeup',png(),'image/png')
    response=client.get(path+'/photos/closeup',headers=AUTH)
    assert response.content==b'jpeg' and response.headers['x-content-type-options']=='nosniff'
    assert client.post(path+'/submit',headers=AUTH,json={'acquisition_date':'2020-01-01','body':''}).json()['status']=='pending'
    assert client.post(path+'/cancel',headers=AUTH,json={}).json()['status']=='cancelled'


@pytest.mark.parametrize('case,status',[('missing',401),('invalid',401),('unverified',403),('disabled',403),('unavailable',503)])
def test_invalid_identity_never_reaches_applications(api,case,status):
    client,verifier,service=api;headers=AUTH
    if case=='missing':headers={}
    if case=='invalid':verifier.verify.side_effect=PermissionError('private')
    if case=='unavailable':verifier.verify.side_effect=RuntimeError('private')
    if case=='unverified':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if case=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError('private')
    response=client.get(BASE,headers=headers)
    assert response.status_code==status and 'private' not in response.text
    service.list.assert_not_called()


def test_reject_oversize_bad_timezone_role_and_request_shape(api):
    client,verifier,service=api
    assert client.get(BASE+'?user_id=1',headers=AUTH).status_code==400
    assert client.get(BASE,headers=AUTH|{'X-YGC-Timezone':'Bad/Zone'}).status_code==400
    assert client.post(BASE,headers=AUTH,json=[]).status_code==400
    assert client.post(BASE+'/'+REV+'/cancel',headers=AUTH,json={'user_id':1}).status_code==400
    assert client.get(BASE+'/'+REV+'/photos/reference',headers=AUTH).status_code==400
    assert client.post(BASE+'/'+REV+'/photos/closeup',headers=AUTH|{'Content-Type':'image/png'},content=b'x'*(8*1024*1024+1)).status_code==413
    service.list.assert_not_called();service.start.assert_not_called();service.upload.assert_not_called();service.image.assert_not_called();service.cancel.assert_not_called()


def test_date_timezone_reaches_worker_and_does_not_leak_between_requests(api):
    from ygc.claim_dates import viewer_timezone
    client,verifier,service=api
    service.start.side_effect=lambda actor,data:{'timezone':viewer_timezone.get().key}
    assert client.post(BASE,headers=AUTH|{'X-YGC-Timezone':'Asia/Tokyo'},json={}).json()=={'timezone':'Asia/Tokyo'}
    assert client.post(BASE,headers=AUTH,json={}).json()=={'timezone':'UTC'}


def test_listing_known_serial_date_and_exact_fields():
    good=dict(manufacturer=' Fender ',serial_number=' TEST123 ',occurred_at='2020-01-01')
    assert listing_input(good)['manufacturer']=='Fender'
    for change in ({'manufacturer':' '},{'serial_number':'unknown'},{'serial_number':'---'},{'occurred_at':'9999-01-01'},{'applicant_id':1}):
        with pytest.raises(ValueError):listing_input(good|change)
    for value in ('../photo','A'*32,True):
        with pytest.raises(ValueError):revision_id(value)


def test_restore_checks_both_private_photos_and_exact_storage_generation():
    store=Storage();ref=store.put('content',b'image',content_type='image/jpeg')
    row=dict(images=json.dumps(dict(closeup=encode_reference(ref),overview=encode_reference(ref))),image_meta=json.dumps(dict(storage='gcs-content-v1')),status='pending')
    verify_restored_applications(store,[row])
    with pytest.raises(ValueError):verify_restored_applications(store,[row|{'images':None}])
    store.delete(ref)
    with pytest.raises(KeyError):verify_restored_applications(store,[row])


def test_retry_requires_canonical_applicant_and_empty_payload(api):
    client, verifier, service=api
    service.retry.return_value={'status':'pending'}
    path=BASE+'/'+REV+'/retry'
    assert client.post(path,headers=AUTH,json={}).json()=={'status':'pending'}
    service.retry.assert_called_once_with('canonical',REV)
    assert client.post(path,headers=AUTH,json={'applicant_id':2}).status_code==400
    verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    assert client.post(path,headers=AUTH,json={}).status_code==403
    assert service.retry.call_count==1


@pytest.mark.parametrize('method,path,payload,operation',[
    ('get',BASE,None,'list'),
    ('post',BASE,{'kind':'acquire','individual_id':'12'},'start'),
    ('post',BASE+'/'+REV+'/cancel',{},'cancel'),
    ('post',BASE+'/'+REV+'/retry',{},'retry'),
    ('post',BASE+'/'+REV+'/submit',{'acquisition_date':'2020-01-01'},'submit'),
    ('get',BASE+'/'+REV+'/photos/closeup',None,'image'),
    ('post',BASE+'/'+REV+'/photos/closeup',None,'upload'),
])
@pytest.mark.parametrize('restriction',['service','account'])
def test_application_service_mode_denial_is_distinct_from_authorization(api,method,path,payload,operation,restriction):
    from ygc.db.postgres_operations import ServiceRestricted
    client,verifier,service=api
    getattr(service,operation).side_effect=(ServiceRestricted if restriction=='service' else PermissionError)('Private reason')
    options={'headers':AUTH}
    if operation=='upload':options={'headers':AUTH|{'Content-Type':'image/png'},'content':png()}
    elif method=='post':options['json']=payload
    response=getattr(client,method)(path,**options)
    assert response.status_code==403
    assert response.headers['cache-control']=='private, no-store'
    assert response.headers['x-content-type-options']=='nosniff'
    assert 'Private reason' not in response.text
    if restriction=='service':assert response.json()=={'detail':{'code':'service_restricted'}}
    else:assert isinstance(response.json()['detail'],str)


@pytest.mark.parametrize('mode,writable',[('normal',True),('read_only',False),('admin_only',True)])
def test_application_list_permission_comes_from_locked_read_transaction(monkeypatch,mode,writable):
    from contextlib import contextmanager
    from ygc.cloud_applications import CloudApplications
    from ygc import cloud_applications as module
    active=[]
    con=Mock()
    con.execute.return_value.fetchall.return_value=[]
    operations=Mock()

    @contextmanager
    def access(kind,actor):
        assert kind=='user_read' and actor=='canonical'
        active.append('locked')
        try:yield None,{'mode':mode},{'id':7}
        finally:active.pop()

    @contextmanager
    def content(actor,ids):
        assert active==['locked'] and actor=='canonical' and ids==(7,)
        yield con,{'id':12}
        assert active==['locked']

    @contextmanager
    def connect(settings,target):
        assert target=='operations'
        yield Mock()

    operations.access.side_effect=access
    accounts=Mock();accounts.content_transaction.side_effect=content
    monkeypatch.setattr(module,'connect',connect)
    monkeypatch.setattr(module,'PostgresAccounts',lambda settings:accounts)
    result=CloudApplications(None,operations,None).list('canonical')
    assert result=={'items':[],'can_write':writable}
    assert active==[]
    operations.access.assert_called_once_with('user_read','canonical')
