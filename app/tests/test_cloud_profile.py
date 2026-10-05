from copy import deepcopy
import pytest
from ygc.cloud_profile import validate

BODY=dict(revision='1',fields=dict(display_name=' Name ',location_country=' Japan ',location_region=' Tokyo ',bio=' Bio\nline '))


def test_profile_validation_trim_and_multiline():
    version,fields=validate(deepcopy(BODY))
    assert version==1 and fields==dict(display_name='Name',location_country='Japan',location_region='Tokyo',bio='Bio\nline')
    assert BODY['fields']['display_name']==' Name '


@pytest.mark.parametrize('change',['role','password','missing','empty','long_name','long_bio','control','null','revision','zero'])
def test_profile_rejects_invalid_values(change):
    body=deepcopy(BODY)
    if change in ('role','password'):body['fields'][change]='injected'
    if change=='missing':body['fields'].pop('bio')
    if change=='empty':body['fields']['display_name']='  '
    if change=='long_name':body['fields']['display_name']='n'*121
    if change=='long_bio':body['fields']['bio']='n'*2001
    if change=='control':body['fields']['location_country']='x\0'
    if change=='null':body['fields']['bio']=None
    if change=='revision':body['revision']=1
    if change=='zero':body['revision']='0'
    with pytest.raises(ValueError):validate(body)
