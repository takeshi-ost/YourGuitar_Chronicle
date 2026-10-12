import json
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ygc.cloud_account_routes import account_router
from ygc.cloud_participants import ParticipantAdmission, participant_subjects
from ygc.cloud_registration import DOCUMENTS
from ygc.identity_platform import VerifiedIdentity


@pytest.mark.parametrize('value', ['', 'null', '{}', '[]', '["*"]', '[1]', '[true]',
    '[" "]', '["uid "]', '["uid","uid"]', '["\\u0000"]', json.dumps(['x'*129]),
    json.dumps([str(i) for i in range(201)])])
def test_bad_explicit_policy_fails_closed(monkeypatch, value):
    monkeypatch.setenv('YGC_CLOSED_TEST_PARTICIPANTS', value)
    with pytest.raises(ValueError, match='Invalid closed-test'):
        participant_subjects()


def test_policy_is_explicit_and_does_not_publish_subjects(monkeypatch):
    monkeypatch.delenv('YGC_CLOSED_TEST_PARTICIPANTS', raising=False)
    assert participant_subjects() is None
    monkeypatch.setenv('YGC_CLOSED_TEST_PARTICIPANTS', '["member", "admin"]')
    assert participant_subjects() == frozenset(('member', 'admin'))


def test_factory_rejects_bad_policy_before_opening_identity_sdk(monkeypatch):
    from ygc import cloud_account_api as api
    monkeypatch.setenv('YGC_CLOSED_TEST_PARTICIPANTS','[]')
    create=Mock()
    monkeypatch.setattr(api,'IdentityPlatformIdentity',create)
    with pytest.raises(ValueError):api.create_app(Mock(),project_id='test-project')
    create.assert_not_called()


def test_staging_cannot_accidentally_start_with_omitted_policy(monkeypatch):
    from ygc import cloud_account_api as api
    monkeypatch.delenv('YGC_CLOSED_TEST_PARTICIPANTS',raising=False)
    with pytest.raises(ValueError,match='explicit closed-test'):
        api.create_app(Mock(),project_id='your-guitar-chronicle-staging')


def setup(subjects, *, subject='member', role='member'):
    verifier = Mock()
    verifier.verify.return_value = VerifiedIdentity('https://securetoken.google.com/test-project', subject, '', True)
    verifier.accounts.resolve_identity.return_value = verifier.accounts.ensure_identity.return_value = {
        'id':7,'app_user_id':'stable-account','display_name':'Participant','account_type':'user','role':role}
    @contextmanager
    def request_identity(token, identity):
        yield
    verifier.verified_request = request_identity
    app = FastAPI()
    app.add_middleware(ParticipantAdmission, verifier=verifier, subjects=frozenset(subjects))
    app.include_router(account_router(verifier, DOCUMENTS))
    @app.get('/api/public/guitars')
    def public(): return {'public':True}
    @app.get('/api/service/status')
    def status(): return {'mode':'normal','message':''}
    @app.post('/api/review/mcp')
    def review(): return {'separate_worker_boundary':True}
    return app, verifier


AUTH = {'Authorization':'Bearer already-issued-token'}


def test_participant_can_register_and_restore_canonical_account():
    app, verifier = setup(['member'])
    with TestClient(app) as client:
        assert client.get('/api/auth/me',headers=AUTH).json()['user']['app_user_id']=='stable-account'
        response=client.post('/api/auth/register',headers=AUTH,json={'display_name':'Participant','account_type':'user',
            'terms_accepted':True,'privacy_accepted':True,'terms_version':DOCUMENTS['terms']['version'],
            'privacy_version':DOCUMENTS['privacy']['version']})
        assert response.status_code==200
    verifier.accounts.ensure_identity.assert_called_once()


def test_removed_subject_is_rejected_with_same_token_and_without_account_changes():
    allowed, _ = setup(['member'])
    removed, verifier = setup(['admin'])
    with TestClient(allowed) as client:
        assert client.get('/api/auth/me',headers=AUTH).status_code==200
    with TestClient(removed) as client:
        for method,path in [('GET','/api/auth/me'),('POST','/api/auth/register'),('GET','/api/service/status')]:
            response=client.request(method,path,headers=AUTH)
            assert response.status_code==403
            assert response.json()['code']=='closed_test_participant_required'
            assert response.headers['cache-control']=='private, no-store'
            assert 'already-issued-token' not in response.text
        assert client.get('/api/public/guitars').status_code==200
        assert client.get('/api/auth/registration').status_code==200
    verifier.accounts.ensure_identity.assert_not_called()
    verifier.accounts.resolve_identity.assert_not_called()


def test_admin_role_never_bypasses_participant_policy():
    app, verifier=setup(['member'],subject='admin',role='admin')
    with TestClient(app) as client:
        assert client.get('/api/auth/me',headers=AUTH).status_code==403
    verifier.accounts.resolve_identity.assert_not_called()


def test_invalid_or_unavailable_verification_never_downgrades_to_guest():
    app, verifier=setup(['member'])
    with TestClient(app) as client:
        verifier.verify.side_effect=PermissionError('private token')
        assert client.get('/api/public/guitars',headers=AUTH).status_code==401
        verifier.verify.side_effect=RuntimeError('private connection')
        response=client.get('/api/auth/me',headers=AUTH)
        assert response.status_code==503 and 'private connection' not in response.text
        assert client.get('/api/public/guitars').status_code==200


def test_worker_keeps_its_separate_verifier_and_user_headers_are_not_checked_as_worker_identity():
    app, verifier=setup(['member'])
    with TestClient(app) as client:
        assert client.post('/api/review/mcp',headers=AUTH).status_code==200
    verifier.verify.assert_not_called()


def test_all_mounted_user_api_routes_reject_before_private_reads_or_writes(monkeypatch):
    from ygc import cloud_account_api as api
    monkeypatch.setenv('YGC_CLOSED_TEST_PARTICIPANTS','["permitted"]')
    accounts,verifier=Mock(),Mock()
    verifier.verify.return_value=VerifiedIdentity('verified','outsider','',True)
    monkeypatch.setattr(api,'PostgresAccounts',Mock(return_value=accounts))
    monkeypatch.setattr(api,'IdentityPlatformIdentity',Mock(return_value=verifier))
    from ygc.cloud_disputes import CloudDisputes
    monkeypatch.setattr(CloudDisputes,'check_schema',Mock())
    app=api.create_app(Mock(),project_id='test-project')
    seen=0
    with TestClient(app) as client:
        for route_path, methods in app.openapi()['paths'].items():
            if not route_path.startswith('/api/') or route_path=='/api/review/mcp':continue
            path=route_path
            import re
            path=re.sub(r'\{[^}]+\}','1',path)
            for method in methods:
                if method not in ('get','post','put','patch','delete'):continue
                response=client.request(method,path,headers=AUTH)
                assert response.status_code==403,(method,path,response.status_code)
                assert response.json()['code']=='closed_test_participant_required'
                seen+=1
    assert seen>80
    accounts.ensure_identity.assert_not_called()
    accounts.resolve_identity.assert_not_called()
