from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_review_identity import ReviewIdentity
from ygc.cloud_review_gateway import review_gateway,TOOL
from ygc.cloud_review_bridge import Bridge

URL='https://ygc-staging-test-an.a.run.app'
EMAIL='ygc-staging-review@ygc-test-project.iam.gserviceaccount.com'
SUBJECT='123456789012345678901'


def test_google_signature_audience_and_exact_worker_are_required(monkeypatch):
    verify=Mock(return_value=dict(iss='https://accounts.google.com',aud=URL,sub=SUBJECT,email=EMAIL,email_verified=True))
    monkeypatch.setattr('ygc.cloud_review_identity.verify_oauth2_token',verify)
    identity=ReviewIdentity(URL,EMAIL,SUBJECT)
    assert identity.verify('opaque')==SUBJECT
    assert verify.call_args.kwargs['audience']==URL
    for key,bad in [('iss','https://securetoken.google.com/ygc-test-project'),('aud','other'),('sub','another'),('email','admin@example.invalid'),('email_verified',False)]:
        saved=verify.return_value;verify.return_value=saved|{key:bad}
        with pytest.raises(PermissionError):identity.verify('opaque')
        verify.return_value=saved
    verify.side_effect=ValueError('private token')
    with pytest.raises(PermissionError,match='invalid'):identity.verify('opaque')
    identity.close()


@pytest.mark.parametrize('url',[URL+'/path',URL+'?x=1','http://localhost:8000','https://evil.invalid',URL.replace('https://','https://user@')])
def test_bridge_never_sends_credentials_to_an_untrusted_url(url):
    with pytest.raises(ValueError):Bridge(url,EMAIL)


def test_authenticated_diagnostic_does_not_claim_or_read_applications():
    verifier=Mock();app=FastAPI();app.include_router(review_gateway(verifier))
    headers={'Authorization':'Bearer opaque'}
    with TestClient(app) as client:
        assert client.post('/api/review/mcp',json={}).status_code==401
        response=client.post('/api/review/mcp',headers=headers,json=dict(jsonrpc='2.0',id=1,method='tools/list'))
        assert response.status_code==200 and [t['name'] for t in response.json()['result']['tools']]==[TOOL]
        response=client.post('/api/review/mcp',headers=headers,json=dict(jsonrpc='2.0',id=2,method='tools/call',params=dict(name=TOOL,arguments={})))
        assert '"queues_connected": false' in response.json()['result']['content'][0]['text']
        assert response.headers['cache-control']=='private, no-store'
        verifier.verify.side_effect=PermissionError('private')
        response=client.post('/api/review/mcp',headers=headers,json=dict(jsonrpc='2.0',id=3,method='tools/list'))
        assert response.status_code==401 and 'private' not in response.text


def test_bridge_refreshes_short_lived_credentials_without_retrying_writes(monkeypatch):
    import httpx
    monkeypatch.setattr('ygc.cloud_review_bridge.subprocess.run',Mock(return_value=Mock(returncode=0,stdout='source-token')))
    calls=[]
    def handle(request):
        calls.append(request)
        if request.url.host=='iamcredentials.googleapis.com':return httpx.Response(200,json={'token':'signed-token'})
        return httpx.Response(401)
    bridge=Bridge(URL,EMAIL,client=httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(httpx.HTTPStatusError):bridge.send(dict(jsonrpc='2.0',id=1,method='ping'))
    assert len(calls)==2 and calls[1].headers['Authorization']=='Bearer signed-token' and bridge.token is None
    bridge.close()
