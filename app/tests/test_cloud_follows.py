"""Authentication, HTTP and privacy contracts for member Follow routes."""
from unittest.mock import Mock
import pytest
from ygc.cloud_follows import AuthenticatedFollows, CloudFollows, target_id
from ygc.identity_platform import VerifiedIdentity


@pytest.mark.parametrize('target', [True, False, None, 0, -1, 2**63, '2', 1.5, {}, []])
def test_invalid_targets(target):
    with pytest.raises(ValueError):
        target_id(target)


@pytest.mark.parametrize('value', [None, 0, 1, 'true', {}, []])
def test_follow_requires_boolean(value):
    operations = Mock()
    with pytest.raises(ValueError):
        CloudFollows(None, operations).set_following('canonical', 2, value)
    operations.account_access.assert_not_called()


@pytest.mark.parametrize('token', [None, '', ' token', 'token ', 'x' * 16385, 123])
def test_invalid_credentials_never_resolve_or_write(token):
    verifier, service = Mock(), Mock()
    with pytest.raises(PermissionError):
        AuthenticatedFollows(verifier, service).set_following(token, 2, True)
    verifier.verify.assert_not_called()
    service.set_following.assert_not_called()


def test_server_identity_is_the_only_actor():
    verifier, service = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', 'tenant', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical-uuid'}
    facade = AuthenticatedFollows(verifier, service)
    facade.set_following('synthetic-token', 2, True)
    service.set_following.assert_called_once_with('canonical-uuid', 2, True)
    facade.state('synthetic-token', 2)
    service.state.assert_called_once_with('canonical-uuid', 2)
    verifier.accounts.resolve_identity.assert_called_with(issuer='issuer', subject='subject', tenant='tenant')


@pytest.mark.parametrize('case', ['invalid', 'unverified', 'inactive'])
def test_identity_failures_do_not_reach_service(case):
    verifier, service = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', case != 'unverified')
    if case == 'invalid': verifier.verify.side_effect = PermissionError()
    if case == 'inactive': verifier.accounts.resolve_identity.side_effect = PermissionError()
    facade = AuthenticatedFollows(verifier, service)
    for action in (lambda: facade.state('token', 2), lambda: facade.set_following('token', 2, True)):
        with pytest.raises(PermissionError): action()
    service.state.assert_not_called()
    service.set_following.assert_not_called()

from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_follow_routes import follow_router
from ygc.cloud_follows import result_projection, FollowTargetMissing, FollowConflict
from ygc.db.postgres_operations import ServiceRestricted

PERSON = {'id': '2', 'display_name': 'Same name', 'icon': None}
PAGE = {'items': [PERSON], 'total': '1', 'next_after': None}
PROFILE = {'person': PERSON, 'following': False, 'is_self': False, 'can_write': True,
           'followers_count': '0', 'following_count': '0'}

@pytest.fixture
def api():
    verifier, service = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical-uuid'}
    service.search.return_value = PAGE
    service.connections.return_value = PAGE
    service.profile.return_value = PROFILE
    service.set_following.return_value = {'target_id': '2', 'following': True}
    app = FastAPI()
    app.include_router(follow_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service

AUTH = {'Authorization': 'Bearer synthetic'}
BASE = '/api/auth/members'

def checked(response, status):
    assert response.status_code == status, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Authorization'
    assert 'secret' not in response.text.lower()
    return response


def test_member_routes_whitelist_and_canonical_identity(api):
    client, _, service = api
    checked(client.get(BASE+'?q=Same&limit=25', headers=AUTH), 200)
    service.search.assert_called_once_with('canonical-uuid', after=0, limit=25, q='Same')
    assert checked(client.get(BASE+'/2', headers=AUTH), 200).json() == PROFILE
    checked(client.get(BASE+'/2/connections/followers?after=1', headers=AUTH), 200)
    service.connections.assert_called_once_with('canonical-uuid', 2, after=1, limit=25, direction='followers')
    checked(client.put(BASE+'/2/following', headers=AUTH, json={'following': True}), 200)
    service.set_following.assert_called_once_with('canonical-uuid', 2, following=True)
    assert result_projection('search', {**PAGE, 'secret': 1, 'items': [{**PERSON, 'email': 'secret'}]}) == PAGE
    assert result_projection('profile', {**PROFILE, 'bio': 'secret'}) == PROFILE


@pytest.mark.parametrize('path', ['', '/2', '/2/connections/following', '/2/avatar'])
@pytest.mark.parametrize('case', ['guest', 'unverified', 'inactive', 'duplicate', 'bad_token'])
def test_guest_and_invalid_identity_cannot_read_any_member_data(api, path, case):
    client, verifier, service = api
    headers = AUTH
    status = 403
    if case == 'guest': headers = {}; status = 401
    if case == 'unverified': verifier.verify.return_value = VerifiedIdentity('i','s','',False)
    if case == 'inactive': verifier.accounts.resolve_identity.side_effect = PermissionError('secret')
    if case == 'duplicate': headers = [*AUTH.items(), *AUTH.items()]; status = 401
    if case == 'bad_token': verifier.verify.side_effect = PermissionError('secret'); status = 401
    checked(client.get(BASE+path, headers=headers), status)
    checked(client.put(BASE+'/2/following', headers=headers, json={'following':True}), status)
    service.search.assert_not_called(); service.profile.assert_not_called(); service.connections.assert_not_called(); service.set_following.assert_not_called()


@pytest.mark.parametrize('query', ['user_id=2','q=a&q=b','after=0','after=01','after=-1','after=9223372036854775808','limit=51','limit=true','q=%00','q='+('x'*121)])
def test_invalid_search(api, query):
    client, _, service = api
    checked(client.get(BASE+'?'+query, headers=AUTH), 400)
    service.search.assert_not_called()


@pytest.mark.parametrize('body', ['null','[]','{}','{"following":1}','{"following":true,"following":false}','{"following":true,"actor":"other"}'])
def test_invalid_follow_json(api, body):
    client, _, service = api
    checked(client.put(BASE+'/2/following', headers={**AUTH,'Content-Type':'application/json'}, content=body), 400)
    service.set_following.assert_not_called()


def test_cross_origin_and_hidden_profile_routes(api):
    client, _, service = api
    checked(client.put(BASE+'/2/following', headers={**AUTH,'Origin':'https://other.invalid'}, json={'following':True}), 403)
    checked(client.put(BASE+'/2/following', headers={**AUTH,'Sec-Fetch-Site':'cross-site'}, json={'following':True}), 403)
    for path in ('/api/public/members','/api/public/members/2/avatar','/api/auth/members/2/favorites'):
        assert client.get(path, headers=AUTH).status_code == 404
    checked(client.request('GET',BASE,headers=AUTH,content='{}'),400)
    checked(client.put(BASE+'/2/following',headers={**AUTH,'Content-Type':'application/json'},content='x'*1025),413)
    service.set_following.assert_not_called()


@pytest.mark.parametrize('error,status', [(FollowTargetMissing('secret'),404),(FollowConflict('secret'),409),(ServiceRestricted('secret'),403),(RuntimeError('secret'),503)])
def test_errors_are_private(api,error,status):
    client,_,service=api
    service.profile.side_effect=error
    checked(client.get(BASE+'/2',headers=AUTH),status)


@pytest.mark.parametrize('person', [{**PERSON,'icon':'https://private.invalid/photo'},{**PERSON,'id':2},{**PERSON,'display_name':None}])
def test_no_photo_or_malformed_person_can_escape(api,person):
    client,_,service=api
    service.search.return_value={**PAGE,'items':[person]}
    checked(client.get(BASE,headers=AUTH),503)


def test_avatar_uses_canonical_auth_and_never_redirects_or_caches(api):
    from ygc.cloud_avatar import AvatarMissing, normalize_image
    from test_cloud_avatar import png
    client, _, service = api
    data = normalize_image(png(), 'image/png')
    service.avatar.return_value = data
    response = checked(client.get(BASE+'/2/avatar', headers={**AUTH, 'If-None-Match':'old', 'Range':'bytes=0-2'}), 200)
    assert response.content == data
    assert response.headers['content-type'] == 'image/jpeg'
    assert response.headers['cross-origin-resource-policy'] == 'same-origin'
    assert 'location' not in response.headers and 'etag' not in response.headers
    service.avatar.assert_called_once_with('canonical-uuid', 2)
    service.avatar.side_effect = AvatarMissing()
    checked(client.get(BASE+'/2/avatar', headers=AUTH), 404)
    checked(client.get(BASE+'/2/avatar?token=synthetic', headers=AUTH), 400)
    checked(client.get(BASE+'/2/avatar', cookies={'token':'synthetic'}), 401)
    checked(client.request('GET',BASE+'/2/avatar',headers=AUTH,content='{}'),400)
