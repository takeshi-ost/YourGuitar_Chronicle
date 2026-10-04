from unittest.mock import Mock

import pytest

from ygc.identity_platform import IdentityPlatformIdentity
from ygc.platform_boundaries import IdentityPlatformReplacement

PROJECT = 'ygc-test-project'
ISSUER = 'https://securetoken.google.com/' + PROJECT


@pytest.fixture
def sdk(monkeypatch):
    firebase_admin = pytest.importorskip('firebase_admin')
    from firebase_admin import auth, tenant_mgt
    monkeypatch.delenv('FIREBASE_AUTH_EMULATOR_HOST', raising=False)
    app = object()
    initialize = Mock(return_value=app)
    delete = Mock()
    verify = Mock(return_value={'sub': 'subject', 'iss': ISSUER, 'aud': PROJECT, 'firebase': {}})
    tenant_client = Mock(verify_id_token=verify)
    tenant_factory = Mock(return_value=tenant_client)
    monkeypatch.setattr(firebase_admin, 'initialize_app', initialize)
    monkeypatch.setattr(firebase_admin, 'delete_app', delete)
    monkeypatch.setattr(auth, 'verify_id_token', verify)
    monkeypatch.setattr(tenant_mgt, 'auth_for_tenant', tenant_factory)
    return initialize, delete, verify, tenant_factory, app


@pytest.fixture
def accounts():
    return Mock(resolve_identity=Mock(return_value={'id': 7, 'app_user_id': 'canonical-uuid'}))


def test_verified_identity_uses_live_registry_and_revocation(sdk, accounts):
    initialize, delete, verify, _, app = sdk
    identity = IdentityPlatformReplacement(accounts, project_id=PROJECT)
    actor = identity.resolve(bearer_token='opaque-token', prototype_user_id=7)
    assert (actor.user_id, actor.app_user_id, actor.subject, actor.verified) == (7, 'canonical-uuid', 'subject', True)
    verify.assert_called_once_with('opaque-token', app=app, check_revoked=True)
    accounts.resolve_identity.assert_called_once_with(issuer=ISSUER, subject='subject', tenant='')
    identity.resolve(bearer_token='opaque-token')
    assert accounts.resolve_identity.call_count == 2
    assert initialize.call_args.kwargs['options'] == {'projectId': PROJECT, 'httpTimeout': 10}
    identity.close()
    identity.close()
    delete.assert_called_once_with(app)
    with pytest.raises(RuntimeError):
        identity.resolve(bearer_token='opaque-token')


@pytest.mark.parametrize('claims', [None, {}, {'sub': 'subject', 'iss': ISSUER, 'aud': PROJECT, 'firebase': {'tenant': 'other'}},
    {'sub': 'subject', 'iss': ISSUER, 'aud': 'other', 'firebase': {}},
    {'sub': 'subject', 'iss': 'other', 'aud': PROJECT, 'firebase': {}},
    {'sub': '', 'iss': ISSUER, 'aud': PROJECT, 'firebase': {}},
    {'sub': 'x' * 129, 'iss': ISSUER, 'aud': PROJECT, 'firebase': {}}])
def test_wrong_project_tenant_or_subject_never_reads_accounts(sdk, accounts, claims):
    sdk[2].return_value = claims
    identity = IdentityPlatformIdentity(accounts, project_id=PROJECT)
    with pytest.raises(PermissionError):
        identity.resolve(bearer_token='token')
    accounts.resolve_identity.assert_not_called()


@pytest.mark.parametrize('token', [None, '', ' ', 123])
def test_missing_token_never_calls_sdk(sdk, accounts, token):
    identity = IdentityPlatformIdentity(accounts, project_id=PROJECT)
    with pytest.raises(PermissionError):
        identity.resolve(bearer_token=token)
    sdk[2].assert_not_called()


def test_sdk_rejection_hides_credentials(sdk, accounts):
    sdk[2].side_effect = ValueError('secret-token-value')
    identity = IdentityPlatformIdentity(accounts, project_id=PROJECT)
    with pytest.raises(PermissionError) as error:
        identity.resolve(bearer_token='token')
    assert 'secret-token-value' not in str(error.value)
    accounts.resolve_identity.assert_not_called()


def test_tenant_client_and_no_client_id_impersonation(sdk, accounts):
    sdk[2].return_value['firebase'] = {'tenant': 'tenant-A'}
    identity = IdentityPlatformIdentity(accounts, project_id=PROJECT, tenant='tenant-A')
    sdk[3].assert_called_once_with('tenant-A', app=sdk[4])
    with pytest.raises(PermissionError):
        identity.resolve(bearer_token='token', prototype_user_id=8)
    sdk[2].assert_called_once_with('token', check_revoked=True)


def test_disabled_or_unknown_account_cannot_authenticate(sdk, accounts):
    accounts.resolve_identity.side_effect = PermissionError('Account is not available.')
    identity = IdentityPlatformIdentity(accounts, project_id=PROJECT)
    with pytest.raises(PermissionError):
        identity.resolve(bearer_token='token')


def test_custom_claims_do_not_grant_admin(sdk, accounts):
    sdk[2].return_value.update(admin=True, role='admin', user_id=99)
    actor = IdentityPlatformIdentity(accounts, project_id=PROJECT).resolve(bearer_token='token')
    assert actor.user_id == 7
    assert not hasattr(actor, 'role')


def test_failed_tenant_initialization_releases_app(sdk, accounts):
    sdk[3].side_effect = ValueError('Invalid tenant configuration')
    with pytest.raises(ValueError):
        IdentityPlatformIdentity(accounts, project_id=PROJECT, tenant='invalid')
    sdk[1].assert_called_once_with(sdk[4])


def test_emulator_rejected_before_and_after_initialization(sdk, accounts, monkeypatch):
    monkeypatch.setenv('FIREBASE_AUTH_EMULATOR_HOST', 'localhost:9099')
    with pytest.raises(ValueError):
        IdentityPlatformIdentity(accounts, project_id=PROJECT)
    sdk[0].assert_not_called()
    monkeypatch.delenv('FIREBASE_AUTH_EMULATOR_HOST')
    identity = IdentityPlatformIdentity(accounts, project_id=PROJECT)
    monkeypatch.setenv('FIREBASE_AUTH_EMULATOR_HOST', '')
    with pytest.raises(ValueError):
        identity.resolve(bearer_token='token')
    sdk[2].assert_not_called()


@pytest.mark.parametrize('project', ['', 'https://project', 'project with spaces'])
def test_project_configuration_required(sdk, accounts, project):
    with pytest.raises(ValueError):
        IdentityPlatformIdentity(accounts, project_id=project)
    sdk[0].assert_not_called()


@pytest.mark.parametrize('case', ['valid', 'expired', 'bad-signature', 'revoked', 'disabled'])
def test_real_sdk_signed_tokens_without_network(monkeypatch, accounts, case):
    """Keep SDK signature/expiry/revocation checks real; replace external I/O only."""
    import time
    from types import SimpleNamespace
    firebase_admin = pytest.importorskip('firebase_admin')
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from google.auth.credentials import AnonymousCredentials
    from google.oauth2 import id_token
    from firebase_admin import _auth_client

    monkeypatch.delenv('FIREBASE_AUTH_EMULATOR_HOST', raising=False)
    initialize = firebase_admin.initialize_app
    monkeypatch.setattr(firebase_admin, 'initialize_app',
                        lambda **kwargs: initialize(credential=AnonymousCredentials(), **kwargs))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setattr(id_token, '_fetch_certs', lambda *args, **kwargs: {'test-key': public})
    at = int(time.time())
    user = SimpleNamespace(disabled=case == 'disabled',
                           tokens_valid_after_timestamp=(at + 60) * 1000 if case == 'revoked' else 0)
    monkeypatch.setattr(_auth_client.Client, 'get_user', lambda *args, **kwargs: user)
    claims = {'iss': ISSUER, 'aud': PROJECT, 'sub': 'subject', 'firebase': {},
              'iat': at - 120, 'auth_time': at - 120, 'exp': at - 60 if case == 'expired' else at + 3600}
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048) if case == 'bad-signature' else key
    token = jwt.encode(claims, signing, algorithm='RS256', headers={'kid': 'test-key'})
    identity = IdentityPlatformIdentity(accounts, project_id=PROJECT)
    try:
        if case == 'valid':
            assert identity.resolve(bearer_token=token).verified
        else:
            with pytest.raises(PermissionError):
                identity.resolve(bearer_token=token)
            accounts.resolve_identity.assert_not_called()
    finally:
        identity.close()
