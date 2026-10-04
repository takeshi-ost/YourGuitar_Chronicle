from dataclasses import replace
from types import SimpleNamespace
import pytest
pytest.importorskip('google.cloud.storage')
from google.api_core.exceptions import NotFound, PreconditionFailed
from ygc.cloud_storage import CloudStorage, StorageSettings, ObjectReference, MARKER, MARKER_DATA, MAX_BYTES
from ygc import storage_probe_job


class Client:
    def __init__(self):self.objects={};self.calls=[];self.revision=0;self.closed=False
    def bucket(self, name):return SimpleNamespace(blob=lambda key,generation=None:Blob(self,name,key,generation))
    def close(self):self.closed=True


class Blob:
    def __init__(self,client,bucket,name,generation):
        self.client=client;self.key=(bucket,name);self.generation=generation;self.content_encoding=None
    def current(self,condition=None):
        row=self.client.objects.get(self.key)
        if row is None or (self.generation is not None and row['generation']!=self.generation):raise NotFound('private reference')
        if condition is not None and row['generation']!=condition:raise PreconditionFailed('private generation')
        return row
    def upload_from_string(self,data,**kwargs):
        self.client.calls.append(('upload',self.key,kwargs))
        if kwargs.get('if_generation_match')==0 and self.key in self.client.objects:raise PreconditionFailed('already exists')
        self.client.revision+=1;self.generation=self.client.revision
        self.client.objects[self.key]=dict(generation=self.generation,data=data,content_type=kwargs.get('content_type','text/plain'))
    def reload(self,**kwargs):
        self.client.calls.append(('reload',self.key,kwargs));row=self.current(kwargs.get('if_generation_match'))
        self.size=len(row['data']);self.content_type=row['content_type'];self.generation=row['generation']
    def download_as_bytes(self,**kwargs):
        self.client.calls.append(('download',self.key,kwargs));return self.current(kwargs.get('if_generation_match'))['data']
    def delete(self,**kwargs):
        self.client.calls.append(('delete',self.key,kwargs));self.current(kwargs.get('if_generation_match'));del self.client.objects[self.key]


@pytest.fixture
def store(monkeypatch):
    monkeypatch.delenv('STORAGE_EMULATOR_HOST',raising=False)
    return CloudStorage(StorageSettings('test-project','test-content','test-accounts'),client=Client())


def test_private_immutable_objects_separate_scopes_and_pin_generations(store,monkeypatch):
    monkeypatch.setattr('ygc.cloud_storage.uuid.uuid4',lambda:SimpleNamespace(hex='a'*32))
    a=store.put('content',b'content',content_type='image/png');b=store.put('accounts',b'avatar',content_type='image/png')
    assert a.name==b.name and store.get(a)==b'content' and store.get(b)==b'avatar'
    with pytest.raises(PreconditionFailed):store.put('content',b'replacement',content_type='image/png')
    assert store.get(a)==b'content'
    for method,key,kwargs in store.client.calls:
        if method=='upload':assert kwargs['if_generation_match']==0 and kwargs['checksum']=='crc32c' and kwargs['retry'] is None and 'predefined_acl' not in kwargs
        if method=='download':assert kwargs['if_generation_match'] in (a.generation,b.generation) and kwargs['raw_download'] and kwargs['checksum']=='crc32c'
    store.delete(a);assert store.get(b)==b'avatar'
    with pytest.raises(NotFound):store.get(a)


def test_stale_reference_never_reads_or_deletes_replacement(store):
    a=store.put('content',b'old',content_type='image/png')
    blob=store._blob('content',a.name);blob.upload_from_string(b'new',content_type='image/png')
    with pytest.raises(NotFound):store.get(a)
    with pytest.raises(NotFound):store.delete(a)
    assert store.client.objects[('test-content',a.name)]['data']==b'new'


@pytest.mark.parametrize('change',[{'name':'../accounts/avatar'}, {'name':'https://example.invalid/x'},
    {'name':MARKER},{'scope':'other'},{'generation':True},{'generation':0},{'size':MAX_BYTES+1},{'content_type':'image/png\r\nx: y'}])
def test_forged_references_rejected_before_storage(store,change):
    with pytest.raises(ValueError):ObjectReference(**(dict(scope='content',name='media/'+'a'*32,generation=1,size=1,content_type='image/png')|change))
    assert not store.client.calls


@pytest.mark.parametrize('data',[b'',b'x'*(MAX_BYTES+1),'text'])
def test_invalid_upload_size_before_any_remote_call(store,data):
    with pytest.raises(ValueError):store.put('content',data,content_type='image/png')
    assert not store.client.calls


def test_metadata_size_mismatch_refuses_download(store):
    a=store.put('content',b'data',content_type='image/png');store.client.calls.clear()
    with pytest.raises(ValueError):store.get(replace(a,size=1))
    assert [c[0] for c in store.client.calls]==['reload']


def test_probe_removes_only_its_objects_preserves_media_and_markers(store):
    ref=store.put('accounts',b'avatar',content_type='image/png')
    assert store.probe()['overwrite_rejected'] is True
    assert store.get(ref)==b'avatar'
    assert {name for bucket,name in store.client.objects}=={MARKER,ref.name}
    store.probe();assert len(store.client.objects)==3
    store.client.calls.clear()
    assert store.status()==dict(backend='gcs',content='available',accounts='available',check='read_only')
    assert {c[0] for c in store.client.calls}=={'reload','download'}


def test_corrupt_marker_not_overwritten_and_no_internal_errors_in_status(store):
    store.probe();store.client.objects[('test-content',MARKER)]['data']=b'corrupt'
    assert store.status()['content']=='unavailable'
    with pytest.raises(ValueError):store.probe()
    assert store.client.objects[('test-content',MARKER)]['data']==b'corrupt'


@pytest.mark.parametrize('env',[{'YGC_MEDIA_BACKEND':'local'},{'YGC_CONTENT_BUCKET':''},
    {'YGC_ACCOUNTS_BUCKET':'test-content'},{'STORAGE_EMULATOR_HOST':'http://private.invalid'}])
def test_explicit_configuration_fails_closed(monkeypatch,env):
    for key,value in dict(YGC_PLATFORM_TARGET='gcp',YGC_MEDIA_BACKEND='gcs',YGC_CONTENT_BUCKET='test-content',YGC_ACCOUNTS_BUCKET='test-accounts').items():monkeypatch.setenv(key,value)
    monkeypatch.delenv('STORAGE_EMULATOR_HOST',raising=False)
    for key,value in env.items():monkeypatch.setenv(key,value)
    with pytest.raises(ValueError):StorageSettings.from_environment('test-project')


def test_probe_job_confirm_project_before_credentials_or_writes(monkeypatch,capsys):
    from unittest.mock import Mock
    monkeypatch.setenv('YGC_GCP_PROJECT_ID','test-project');factory=Mock()
    monkeypatch.setattr(storage_probe_job,'CloudStorage',factory)
    assert storage_probe_job.main(['--confirm-project','other-project'])==1
    factory.assert_not_called();assert capsys.readouterr().err.strip()=='{"status": "failed"}'
