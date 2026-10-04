from datetime import datetime,timezone,timedelta
from unittest.mock import Mock
from types import SimpleNamespace
import uuid
import pytest
from ygc.cloud_maintenance_control import MaintenanceControl,MaintenanceJobClient,public,MaintenanceModeRequired
from ygc.cloud_db_restore import load,self_order
from test_cloud_db_snapshot import archive


def test_restore_load_uses_verified_known_schema():
    data,sha=archive()
    header,rows,sequences=load(data,'accounts',sha)
    assert header['schema_version']==2 and len(rows)==8 and sequences==[]
    with pytest.raises(ValueError):load(data,'chronicle',sha)
    with pytest.raises(ValueError):load(data,'accounts','0'*64)


def test_self_references_reorder_and_reject_missing_cycles():
    assert self_order([{'id':2,'parent':1},{'id':1,'parent':None}],['parent'])==[{'id':1,'parent':None},{'id':2,'parent':1}]
    with pytest.raises(ValueError):self_order([{'id':1,'parent':2},{'id':2,'parent':1}],['parent'])
    with pytest.raises(ValueError):self_order([{'id':1,'parent':3}],['parent'])


@pytest.mark.parametrize('change',[{'target':'unknown'},{'confirmation':'accounts'},{'backup_id':'../escape'},{'request_id':'invalid'},{'action':'delete'},{'extra':'value'}])
def test_control_rejects_invalid_request_before_dispatch(change):
    operations=Mock();client=Mock();control=MaintenanceControl(operations,client)
    data=dict(target='chronicle',action='restore',confirmation='chronicle',backup_id=str(uuid.uuid4()),request_id=str(uuid.uuid4()))|change
    with pytest.raises(ValueError):control.start('actor',data)
    operations.access.assert_not_called();client.start.assert_not_called()


def test_job_args_fixed_and_no_archive_or_actor_in_overrides():
    session=Mock();session.post.return_value.json.return_value={'name':'projects/project/locations/asia-northeast1/operations/operation'}
    client=MaintenanceJobClient('project','asia-northeast1',session=session)
    token=str(uuid.uuid4());client.start('chronicle',token)
    args=session.post.call_args.kwargs['json']['overrides']['containerOverrides'][0]['args']
    assert args==['-m','ygc.cloud_maintenance_job','--confirm-project=project','--request-id='+token]
    with pytest.raises(ValueError):client.start('other',token)


def test_public_status_masks_provider_and_marks_expired_unknown():
    record=dict(request_id='uuid',target='accounts',action='restore',state='running',created_at=(datetime.now(timezone.utc)-timedelta(minutes=31)).isoformat(),actor='private',operation='private')
    result=public(record)
    assert result['retry_allowed'] and result['state']=='unknown' and 'actor' not in result and 'operation' not in result
