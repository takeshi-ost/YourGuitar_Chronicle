from contextlib import contextmanager
from dataclasses import asdict
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ygc import cloud_backup_policy as policy
from ygc.cloud_backup_job import KIND
from test_cloud_db_snapshot import archive
from test_cloud_avatar import Storage


@pytest.mark.parametrize('values',[('unknown',10,False,24),('accounts',0,False,24),('accounts',101,False,24),('accounts',True,False,24),('accounts',10,1,24),('accounts',10,False,0),('accounts',10,False,169)])
def test_policy_rejects_unbounded_or_ambiguous_values(values):
    with pytest.raises(ValueError):policy.validate(*values)


def test_retention_verifies_and_deletes_only_excess_objects_for_selected_target(monkeypatch):
    store=Storage();data,sha=archive();rows=[]
    for i in range(3):
        ref=store.put('accounts',data,content_type='application/gzip')
        rows.insert(0,dict(id=i+1,reason=json.dumps({'kind':KIND,'backup_id':str(i),'target':'accounts','object':asdict(ref),'sha256':sha},separators=(',',':'))))
    image=store.put('accounts',b'image',content_type='image/jpeg')
    con=Mock()
    def execute(sql,params):
        return SimpleNamespace(fetchone=lambda:{'generations':2},fetchall=lambda:[] if isinstance(params[0],str) and 'maintenance_request' in params[0] else rows)
    con.execute.side_effect=execute
    @contextmanager
    def connect(settings,target):assert target=='operations';yield con
    monkeypatch.setattr(policy,'connect',connect)
    assert policy.prune(None,store,'accounts')==1
    assert len(store.deleted)==1 and len(store.objects)==3 and image in store.objects
    updates=[c for c in con.execute.call_args_list if c.args[0].startswith('UPDATE')]
    assert len(updates)==1 and json.loads(updates[0].args[1][0])['deleted_at']


def test_retention_never_deletes_wrong_scope_or_non_backup(monkeypatch):
    store=Storage();ref=store.put('accounts',b'image',content_type='image/jpeg')
    rows=[{'id':1,'reason':'{}'},{'id':2,'reason':json.dumps({'backup_id':'2','object':asdict(ref),'sha256':'bad'})}]
    con=Mock();con.execute.return_value.fetchone.return_value={'generations':1};con.execute.return_value.fetchall.return_value=rows
    con.execute.side_effect=lambda sql,params:SimpleNamespace(fetchone=lambda:{'generations':1},fetchall=lambda:[] if isinstance(params[0],str) and 'maintenance_request' in params[0] else rows)
    @contextmanager
    def connect(settings,target):yield con
    monkeypatch.setattr(policy,'connect',connect)
    with pytest.raises(ValueError):policy.prune(None,store,'accounts')
    assert not store.deleted and ref in store.objects
