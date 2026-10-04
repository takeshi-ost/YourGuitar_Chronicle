from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
from types import SimpleNamespace
from unittest.mock import Mock
import uuid
import pytest
from ygc.cloud_backup_control import BackupControl, BackupJobClient, BackupBusy, REQUEST_KIND
from ygc.cloud_backup_job import KIND


@pytest.fixture
def control():
    rows=[];client=Mock();client.start.return_value='private-operation';client.status.return_value='running'
    class Con:
        commits=0
        def commit(self):self.commits+=1
        def execute(self,sql,params):
            if sql.startswith('SELECT'):
                prefix,key,value=params
                matches=[r for r in rows if r['reason'].startswith(prefix[:-1]) and json.loads(r['reason']).get(key)==value]
                result=matches[-1] if matches else None
            elif sql.startswith('INSERT'):
                result=dict(id=len(rows)+1,reason=params[2]);rows.append(result)
            else:
                rows[params[1]-1]['reason']=params[0];result=None
            return SimpleNamespace(fetchone=lambda:result)
    con=Con();ops=Mock()
    @contextmanager
    def access(kind,actor):yield con,{'mode':'offline'},{}
    ops.access.side_effect=access
    return BackupControl(ops,client),client,rows,con,ops


def test_intent_committed_before_provider_and_duplicate_uuid_never_launches_twice(control):
    controller,client,rows,con,ops=control;token=str(uuid.uuid4())
    def start(target,request):
        assert con.commits==1 and json.loads(rows[0]['reason'])['state']=='starting'
        return 'private-operation'
    client.start.side_effect=start
    first=controller.start('canonical','accounts',token)
    assert first==controller.start('canonical','accounts',token)
    client.start.assert_called_once_with('accounts',token)
    assert set(first)=={'request_id','target','state','created_at'}
    with pytest.raises(ValueError):controller.start('another','accounts',token)
    with pytest.raises(ValueError):controller.start('canonical','chronicle',token)
    with pytest.raises(BackupBusy):controller.start('canonical','accounts',str(uuid.uuid4()))
    assert ops.access.call_args.args==('admin_write','canonical')


def test_provider_timeout_is_persistent_unknown_without_automatic_retry(control):
    controller,client,rows,con,ops=control;token=str(uuid.uuid4())
    client.start.side_effect=TimeoutError('private provider body')
    assert controller.start('canonical','chronicle',token)['state']=='unknown'
    assert controller.start('canonical','chronicle',token)['state']=='unknown'
    assert controller.status('canonical','chronicle')['retry_allowed'] is False
    client.start.assert_called_once();client.status.assert_not_called()
    row=json.loads(rows[0]['reason']);row['created_at']=(datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat();rows[0]['reason']=json.dumps(row,separators=(',',':'))
    assert controller.status('canonical','chronicle')['retry_allowed'] is True
    controller.start('canonical','chronicle',str(uuid.uuid4()))
    assert client.start.call_count==2


def test_success_requires_committed_archive_not_provider_completion(control):
    controller,client,rows,con,ops=control
    token=str(uuid.uuid4());controller.start('canonical','accounts',token)
    client.status.return_value='finished'
    assert controller.status('canonical','accounts')['state']=='failed'
    token=str(uuid.uuid4());controller.start('canonical','accounts',token)
    rows.append(dict(id=3,reason=json.dumps({'kind':KIND,'request_id':token,'target':'accounts'},separators=(',',':'))))
    assert controller.status('canonical','accounts')['state']=='succeeded'
    assert controller.status('canonical','chronicle')=={'target':'chronicle','state':'idle'}


def test_cloud_client_fixed_resource_overrides_and_no_secret_response():
    session=Mock();session.post.return_value.json.return_value={'name':'projects/test-project/locations/asia-northeast1/operations/operation-1'}
    client=BackupJobClient('test-project','asia-northeast1',session=session);token=str(uuid.uuid4())
    operation=client.start('accounts',token)
    kwargs=session.post.call_args.kwargs
    assert session.post.call_args.args[0].endswith('/jobs/ygc-staging-db-backup:run')
    assert kwargs['timeout']==10
    override=kwargs['json']['overrides']['containerOverrides'][0]
    assert override['args'][-1]=='--target=accounts'
    assert override['env']==[{'name':'YGC_BACKUP_REQUEST_ID','value':token}]
    with pytest.raises(ValueError):client.status('projects/foreign-project/locations/asia-northeast1/operations/op')
    session.get.assert_not_called()
    session.get.return_value.json.side_effect=[{'done':True,'response':{'name':client.job+'/executions/exec-1'}},{'runningCount':1}]
    assert client.status(operation)=='running'
    session.get.return_value.json.side_effect=[{'done':True,'response':{'name':client.job+'/executions/exec-1'}},{'completionTime':'now','succeededCount':1}]
    assert client.status(operation)=='finished'
