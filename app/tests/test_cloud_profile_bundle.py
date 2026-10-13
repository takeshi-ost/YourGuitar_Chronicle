from contextlib import contextmanager
from unittest.mock import Mock
import pytest
from ygc.cloud_profile_bundle import CloudProfileBundle

@contextmanager
def access(*args):yield None

def test_bundle_uses_one_canonical_actor_and_bounded_existing_readers():
    u,f=Mock(),Mock();u.operations.account_access.side_effect=access
    u.own_inventory.return_value={'owned':{'items':[{'id':9007199254741009}],'total':1,'next_after':None},'formerly_owned':{'items':[],'total':0,'next_after':None},'summary':{},'signature':{}}
    result=CloudProfileBundle(u,f).own_bootstrap('canonical')
    assert set(result)=={'settings','summary','signature','owned','formerly_owned','favorites'}
    assert result['owned']['items'][0]['id']=='9007199254741009'
    u.own_inventory.assert_called_once_with('canonical')
    f.list.assert_called_once_with('canonical',limit=50)
    u.operations.account_access.assert_called_once_with('user_read','canonical')

def test_bundle_never_returns_partial_private_data_after_revocation():
    u,f=Mock(),Mock();u.own_inventory.return_value={'owned':{'items':[],'total':0,'next_after':None},'formerly_owned':{'items':[],'total':0,'next_after':None},'summary':{},'signature':{}}
    u.operations.account_access.side_effect=PermissionError('revoked')
    with pytest.raises(PermissionError):CloudProfileBundle(u,f).own_bootstrap('canonical')
