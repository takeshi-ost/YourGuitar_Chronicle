from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
from unittest.mock import Mock
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_avatar import CloudAvatar, AvatarMissing, normalize_image, encode_reference, decode_reference
from ygc.cloud_avatar_routes import avatar_router
from ygc.cloud_storage import ObjectReference
from ygc.identity_platform import VerifiedIdentity


def png(size=(800,400)):
    out=BytesIO()
    with Image.new('RGBA',size,(255,0,0,0)) as image:image.save(out,format='PNG')
    return out.getvalue()


class Storage:
    def __init__(self):self.objects={};self.deleted=[];self.next_id=0
    def put(self,scope,data,*,content_type):
        self.next_id+=1
        ref=ObjectReference(scope,'media/'+format(self.next_id,'032x'),1,len(data),content_type)
        self.objects[ref]=data
        return ref
    def get(self,ref):return self.objects[ref]
    def delete(self,ref):self.deleted.append(ref);del self.objects[ref]


class Operations:
    def __init__(self):
        self.account={'avatar_storage_path':None};self.con=Mock();self.failure=None;self.calls=[]
    @contextmanager
    def account_access(self,kind,actor):
        self.calls.append((kind,actor))
        if self.failure=='permission':raise PermissionError()
        yield self.con,{},self.account
        if self.failure=='commit':raise RuntimeError('uncertain commit')


def test_normalize_strips_metadata_resizes_and_flattens():
    data=normalize_image(png(),'image/png')
    with Image.open(BytesIO(data)) as image:
        assert image.format=='JPEG' and image.size==(512,256)
        assert image.mode=='RGB' and image.getpixel((0,0))==(255,255,255)
        assert not image.getexif()


@pytest.mark.parametrize('data,mime',[(b'invalid','image/png'),(png(),'image/jpeg'),(png(),'image/svg+xml'),(png((3000,3000)),'image/png')])
def test_invalid_image_rejected(data,mime):
    with pytest.raises(ValueError):normalize_image(data,mime)


def test_reference_pins_accounts_generation_and_rejects_forgery():
    ref=ObjectReference('accounts','media/'+'a'*32,42,12,'image/jpeg')
    assert decode_reference(encode_reference(ref))==ref
    for bad in (replace(ref,scope='content'),replace(ref,content_type='image/png')):
        with pytest.raises(ValueError):encode_reference(bad)
    for value in ('https://example.invalid/image','/tmp/image','gcs-avatar-v1:{}'):
        with pytest.raises(ValueError):decode_reference(value)


def test_save_audits_same_connection_retains_previous_and_delete_only_clears_pointer():
    ops,store=Operations(),Storage();service=CloudAvatar(ops,store)
    previous=store.put('accounts',b'old',content_type='image/jpeg')
    ops.account['avatar_storage_path']=encode_reference(previous)
    assert service.set('canonical',png(),'image/png',admin=True)=={'has_avatar':True}
    assert ops.calls==[('admin_write','canonical')]
    assert len(ops.con.execute.call_args_list)==2 and len(store.objects)==2 and not store.deleted
    ops.con.reset_mock();service.set('canonical')
    assert ops.con.execute.call_args_list[0].args[1][0] is None
    assert len(store.objects)==2 and not store.deleted


@pytest.mark.parametrize('failure,deleted',[('audit',True),('commit',False)])
def test_rollback_compensates_only_new_object_uncertain_commit_retains(failure,deleted):
    ops,store=Operations(),Storage();service=CloudAvatar(ops,store)
    previous=store.put('accounts',b'old',content_type='image/jpeg')
    ops.account['avatar_storage_path']=encode_reference(previous)
    if failure=='audit':ops.con.execute.side_effect=[None,RuntimeError('audit failed')]
    else:ops.failure='commit'
    with pytest.raises(RuntimeError):service.set('canonical',png(),'image/png')
    assert previous in store.objects and previous not in store.deleted
    assert bool(store.deleted)==deleted


def test_mode_rejection_prevents_any_remote_write():
    ops,store=Operations(),Storage();ops.failure='permission'
    with pytest.raises(PermissionError):CloudAvatar(ops,store).set('canonical',png(),'image/png')
    assert not store.objects


@pytest.fixture
def api():
    verifier=Mock();verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True)
    verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical','role':'member'}
    ops,store=Operations(),Storage();app=FastAPI();app.include_router(avatar_router(verifier,ops,store))
    with TestClient(app) as client:yield client,verifier,ops,store


AUTH={'Authorization':'Bearer token'}


def test_api_binary_upload_uses_canonical_self_and_private_response(api):
    client,verifier,ops,store=api
    assert client.get('/api/auth/avatar',headers=AUTH).status_code==404
    result=client.put('/api/auth/avatar',headers=AUTH|{'Content-Type':'image/png'},content=png())
    assert result.status_code==200 and result.json()=={'has_avatar':True}
    assert ops.calls[-1]==('user_write','canonical')
    ops.account['avatar_storage_path']=encode_reference(next(iter(store.objects)))
    result=client.get('/api/auth/avatar',headers=AUTH)
    assert result.status_code==200 and result.headers['content-type']=='image/jpeg'
    assert result.headers['cache-control']=='private, no-store' and result.headers['x-content-type-options']=='nosniff'
    assert client.delete('/api/auth/avatar',headers=AUTH).status_code==200


@pytest.mark.parametrize('failure,status',[('missing',401),('token',401),('email',403),('disabled',403),('identity',503)])
def test_auth_rejection_never_accesses_images(api,failure,status):
    client,verifier,ops,store=api;headers=AUTH
    if failure=='missing':headers={}
    if failure=='token':verifier.verify.side_effect=PermissionError('secret')
    if failure=='identity':verifier.verify.side_effect=RuntimeError('secret')
    if failure=='email':verifier.verify.return_value=VerifiedIdentity('issuer','subject','',False)
    if failure=='disabled':verifier.accounts.resolve_identity.side_effect=PermissionError('secret')
    result=client.put('/api/auth/avatar',headers=headers|{'Content-Type':'image/png'},content=png())
    assert result.status_code==status and 'secret' not in result.text and not ops.calls and not store.objects


def test_admin_path_and_forged_identifiers(api):
    client,verifier,ops,store=api
    assert client.get('/api/admin/accounts/me/avatar',headers=AUTH).status_code==403
    assert client.put('/api/auth/avatar?user_id=other',headers=AUTH,content=png()).status_code==400
    assert not ops.calls
    verifier.accounts.resolve_identity.return_value['role']='admin'
    assert client.put('/api/admin/accounts/me/avatar',headers=AUTH|{'Content-Type':'image/png'},content=png()).status_code==200
    assert ops.calls==[('admin_write','canonical')]


def test_limit_and_invalid_body_do_not_write(api):
    client,verifier,ops,store=api
    assert client.put('/api/auth/avatar',headers=AUTH|{'Content-Type':'image/png'},content=b'x'*(8*1024*1024+1)).status_code==413
    assert client.put('/api/auth/avatar',headers=AUTH|{'Content-Type':'image/png'},content=b'bad').status_code==400
    assert not store.objects and not ops.calls
