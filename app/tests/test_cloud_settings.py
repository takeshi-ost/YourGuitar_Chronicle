from copy import deepcopy
import pytest
from ygc.cloud_profile import validate_settings, validate_signature
from test_cloud_self_profile import api, AUTH

BODY={'revision':'1','fields':{'display_name':'Alice','location_country':'Japan','location_region':'Tokyo','bio':'Synthetic',
    'account_type':'user','date_of_birth':'2000-01-01','theme':'sunburst_3ply','birth_visibility':'Private','residence_visibility':'Private','bio_visibility':'Members','avatar_visibility':'Followers'}}

@pytest.mark.parametrize('key,value',[('role','admin'),('account_type','admin'),('theme','url(secret)'),('date_of_birth','2100-01-01'),('date_of_birth','2000-02-30'),('birth_visibility',None),('bio_visibility','Everyone')])
def test_settings_reject_authority_and_invalid_values(key,value):
    body=deepcopy(BODY);body['fields'][key]=value
    with pytest.raises((ValueError,TypeError)):validate_settings(body)

@pytest.mark.parametrize('path,body,read,write',[
 ('/api/auth/settings',BODY,'own_settings','edit_own_settings'),
 ('/api/auth/settings/signature',{'previous':None,'individual_id':'9007199254741009'},'own_signature','edit_own_signature')])
def test_settings_self_identity_and_private_routes(api,path,body,read,write):
    client,verifier,service=api
    getattr(service,read).return_value={'private':'synthetic'};getattr(service,write).return_value={'saved':True}
    result=client.get(path,headers=AUTH)
    assert result.status_code==200 and result.headers['cache-control']=='private, no-store'
    getattr(service,read).assert_called_once_with('canonical-member')
    assert client.put(path,json=body,headers=AUTH).status_code==200
    getattr(service,write).assert_called_once_with('canonical-member',body)
    assert client.get(path+'?user_id=2',headers=AUTH).status_code==400
    verifier.verify.side_effect=PermissionError('secret')
    assert client.put(path,json=body,headers=AUTH).status_code==401

@pytest.mark.parametrize('value',[1,'0','9223372036854775808','1\n',False])
def test_signature_identifiers_are_lossless_and_strict(value):
    with pytest.raises((ValueError,TypeError)):validate_signature({'previous':None,'individual_id':value})


def test_self_summary_is_read_only_and_uses_canonical_actor():
    from unittest.mock import Mock
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ygc.cloud_self_profile_routes import self_profile_router
    from ygc.identity_platform import VerifiedIdentity
    verifier,service=Mock(),Mock();verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True);verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical'}
    service.own_summary.return_value={'owned_count':'1','former_count':'2','claim_count':'3'}
    app=FastAPI();app.include_router(self_profile_router(verifier,service));client=TestClient(app)
    response=client.get('/api/auth/profile/summary',headers={'Authorization':'Bearer fixture'})
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    service.own_summary.assert_called_once_with('canonical')
    assert client.get('/api/auth/profile/summary?user_id=2',headers={'Authorization':'Bearer fixture'}).status_code==400
    assert client.put('/api/auth/profile/summary',headers={'Authorization':'Bearer fixture'},json={}).status_code==405
    verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    assert client.get('/api/auth/profile/summary',headers={'Authorization':'Bearer fixture'}).status_code==403


def test_user_chronicle_is_self_only_and_never_accepts_mutation(api):
    client,verifier,service=api
    service.own_chronicle.return_value={'items':[]}
    assert client.get('/api/auth/profile/chronicle',headers=AUTH).status_code==200
    service.own_chronicle.assert_called_once_with('canonical-member')
    assert client.get('/api/auth/profile/chronicle?user_id=2',headers=AUTH).status_code==400
    assert client.put('/api/auth/profile/chronicle',headers=AUTH,json={}).status_code==405
    verifier.verify.side_effect=PermissionError('private')
    assert client.get('/api/auth/profile/chronicle',headers=AUTH).status_code==401
