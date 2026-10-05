from dataclasses import replace
from io import BytesIO
from unittest.mock import Mock
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_content_media import encode_reference,decode_reference,verify_restored_media,MediaConflict
from ygc.cloud_content_media_routes import content_media_router
from ygc.cloud_avatar import normalize_image
from ygc.identity_platform import VerifiedIdentity
from test_cloud_avatar import Storage,png


def test_content_normalization_keeps_detail_and_avatar_size():
    with Image.open(BytesIO(normalize_image(png((2400,1200)),'image/png',max_side=2048))) as image:
        assert image.size==(2048,1024) and image.format=='JPEG' and not image.getexif()
    with Image.open(BytesIO(normalize_image(png((2400,1200)),'image/png'))) as image:assert image.size==(512,256)


def test_restore_requires_existing_content_generation_and_supported_media():
    store=Storage();ref=store.put('content',b'image',content_type='image/jpeg')
    row=dict(storage_path=encode_reference(ref),media_type='image',mime_type='image/jpeg')
    assert decode_reference(row['storage_path'])==ref
    verify_restored_media(store,[row])
    for bad in (replace(ref,scope='accounts'),replace(ref,content_type='image/png')):
        with pytest.raises(ValueError):encode_reference(bad)
    for value in ('/tmp/photo','https://example.invalid/photo','gcs-content-v1:{}',row['storage_path'].replace('"scope":"content"','"scope":"accounts","scope":"content"')):
        with pytest.raises(ValueError):decode_reference(value)
    with pytest.raises(ValueError):verify_restored_media(store,[row|{'media_type':'video'}])
    store.delete(ref)
    with pytest.raises(KeyError):verify_restored_media(store,[row])


@pytest.fixture
def api():
    verifier=Mock();verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True)
    verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical','role':'admin'}
    service=Mock();service.listing.return_value=dict(total='1',items=[dict(id='2',captured_at='2026-10-05')],next_after=None)
    service.get.return_value=b'jpeg';service.upload.return_value=dict(media_id='2',claim_id='3',verification_status='unverified')
    app=FastAPI();app.include_router(content_media_router(verifier,service))
    with TestClient(app) as client:yield client,verifier,service


AUTH={'Authorization':'Bearer token'}
PATH='/api/admin/guitars/1/media'


def test_admin_upload_list_and_private_image_are_bound_to_resource(api):
    client,verifier,service=api
    result=client.post(PATH,headers=AUTH|{'Content-Type':'image/png'},content=png())
    assert result.status_code==200 and result.json()['verification_status']=='unverified'
    service.upload.assert_called_once_with('canonical',1,png(),'image/png')
    result=client.get(PATH+'?after=2',headers=AUTH)
    assert result.status_code==200 and result.json()['total']=='1'
    service.listing.assert_called_once_with('canonical',1,after=2)
    result=client.get(PATH+'/2',headers=AUTH)
    assert result.content==b'jpeg' and result.headers['content-type']=='image/jpeg'
    assert result.headers['cache-control']=='private, no-store' and result.headers['x-content-type-options']=='nosniff'
    service.get.assert_called_once_with('canonical',1,2)


@pytest.mark.parametrize('case,status',[('missing',401),('token',401),('email',403),('member',403),('disabled',403),('identity',503)])
def test_rejected_identity_never_reads_or_writes(api,case,status):
    client,verifier,service=api;headers=AUTH
    if case=='missing':headers={}
    if case=='token':verifier.verify.side_effect=PermissionError('secret')
    if case=='identity':verifier.verify.side_effect=RuntimeError('secret')
    if case=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if case=='member':verifier.accounts.resolve_identity.return_value['role']='member'
    if case=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError('secret')
    result=client.get(PATH,headers=headers)
    assert result.status_code==status and 'secret' not in result.text
    service.listing.assert_not_called();service.get.assert_not_called();service.upload.assert_not_called()


@pytest.mark.parametrize('query',['?after=0','?after=1&after=2','?target=accounts','?after=9223372036854775808'])
def test_invalid_page_does_not_reach_database(api,query):
    client,verifier,service=api
    assert client.get(PATH+query,headers=AUTH).status_code==400
    service.listing.assert_not_called()


def test_upload_limits_and_operation_errors(api):
    client,verifier,service=api
    assert client.post(PATH,headers=AUTH|{'Content-Type':'image/png'},content=b'x'*(8*1024*1024+1)).status_code==413
    assert client.post(PATH,headers=AUTH|{'Content-Type':'image/svg+xml'},content=b'image').status_code==400
    service.upload.assert_not_called()
    service.upload.side_effect=MediaConflict()
    assert client.post(PATH,headers=AUTH|{'Content-Type':'image/png'},content=png()).status_code==409
    from ygc.cloud_guitars import GuitarMissing
    service.get.side_effect=GuitarMissing()
    assert client.get('/api/admin/guitars/99/media/2',headers=AUTH).status_code==404
    service.get.assert_called_once_with('canonical',99,2)
