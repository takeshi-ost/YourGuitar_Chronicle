import re
from unittest.mock import Mock
import pytest
pytest.importorskip('psycopg')
from fastapi.testclient import TestClient
from ygc import cloud_account_runtime as runtime
from ygc import cloud_account_api as api


@pytest.fixture(autouse=True)
def dispute_schema_boundary(monkeypatch):
    from ygc.cloud_disputes import CloudDisputes
    check = Mock()
    monkeypatch.setattr(CloudDisputes, "check_schema", check)
    return check


@pytest.fixture
def environment(monkeypatch):
    values = {'YGC_PLATFORM_TARGET': 'gcp', 'YGC_DATABASE_BACKEND': 'postgres',
              'YGC_IDENTITY_BACKEND': 'identity_platform', 'YGC_IDENTITY_PROJECT_ID': 'test-project',
              'YGC_POSTGRES_HOST': '/cloudsql/test-project:asia-northeast1:db',
              'YGC_POSTGRES_USER': 'ygc_app', 'YGC_POSTGRES_PASSWORD': 'private-password',
              'YGC_FIREBASE_API_KEY': 'public-key',
              'YGC_FIREBASE_AUTH_DOMAIN': 'test-project.firebaseapp.com'}
    monkeypatch.setattr(runtime, 'CloudStorage', Mock(return_value=Mock()))
    values.update(YGC_MEDIA_BACKEND='gcs',YGC_CONTENT_BUCKET='test-project-content',YGC_ACCOUNTS_BUCKET='test-project-accounts')
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize('key,value', [('YGC_PLATFORM_TARGET', 'local'),
    ('YGC_DATABASE_BACKEND', 'sqlite'), ('YGC_IDENTITY_BACKEND', 'dummy'),
    ('YGC_IDENTITY_PROJECT_ID', ''), ('YGC_POSTGRES_HOST', '/cloudsql/other-project:region:db')])
def test_invalid_configuration_never_creates_app(environment, monkeypatch, key, value):
    create = Mock()
    monkeypatch.setattr(runtime, 'create_app', create)
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        runtime.application()
    create.assert_not_called()


def test_startup_and_database_outage(environment, monkeypatch):
    accounts, verifier = Mock(), Mock()
    monkeypatch.setattr(api, 'PostgresAccounts', Mock(return_value=accounts))
    monkeypatch.setattr(api, 'IdentityPlatformIdentity', Mock(return_value=verifier))
    monkeypatch.setattr(api, 'connect', Mock(side_effect=RuntimeError('private-password')))
    with TestClient(runtime.application()) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        response = client.get('/ready')
        assert response.status_code == 503
        assert 'private-password' not in response.text
        assert client.get('/account').status_code == 200
    accounts.check_schema.assert_called_once()
    verifier.close.assert_called_once()


def test_schema_failure_closes_verifier_without_serving(environment, monkeypatch):
    accounts, verifier = Mock(), Mock()
    accounts.check_schema.side_effect = RuntimeError('private-password')
    monkeypatch.setattr(api, 'PostgresAccounts', Mock(return_value=accounts))
    monkeypatch.setattr(api, 'IdentityPlatformIdentity', Mock(return_value=verifier))
    with pytest.raises(RuntimeError, match='database initialization check failed') as error:
        with TestClient(runtime.application()):
            pytest.fail('Invalid schema must prevent startup')
    assert 'private-password' not in str(error.value)
    verifier.close.assert_called_once()


def test_console_serves_only_shell_and_whitelisted_assets(environment, monkeypatch):
    accounts, verifier = Mock(), Mock()
    monkeypatch.setattr(api, 'PostgresAccounts', Mock(return_value=accounts))
    monkeypatch.setattr(api, 'IdentityPlatformIdentity', Mock(return_value=verifier))
    with TestClient(runtime.application()) as client:
        shell = client.get('/console')
        assert shell.status_code == 200 and shell.headers['cache-control'] == 'no-store'
        assert '/assets/cloud-console-page.js' in re.sub(r'/assets/v/[0-9a-f]{64}/', '/assets/', shell.text)
        assert client.get('/assets/cloud-console-page.js').status_code == 200
        assert client.get('/assets/cloud-console.css').status_code == 200
        assert client.get('/assets/pages/console.js').status_code == 404
        assert client.get('/assets/cloud_console_html.html').status_code == 404
        verifier.verify.assert_not_called()
        accounts.resolve_identity.assert_not_called()


def test_public_catalog_shell_does_not_mount_prototype_or_private_assets(environment, monkeypatch):
    accounts, verifier = Mock(), Mock()
    monkeypatch.setattr(api, 'PostgresAccounts', Mock(return_value=accounts))
    monkeypatch.setattr(api, 'IdentityPlatformIdentity', Mock(return_value=verifier))
    with TestClient(runtime.application()) as client:
        for path in ('/', '/guitars/1', '/guitars/9223372036854775807'):
            response = client.get(path)
            assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
            assert '/assets/cloud-public-catalog.js' in re.sub(r'/assets/v/[0-9a-f]{64}/', '/assets/', response.text)
            assert 'cloud-account-page.js' not in response.text
        for path in ('/assets/cloud-public-catalog.js', '/assets/cloud-public-catalog.css', '/assets/product-detail.js', '/assets/list-navigation.js', '/assets/table-columns.js', '/account', '/console'):
            assert client.get(path).status_code == 200
        for path in ('/guitars/0', '/guitars/9223372036854775808', '/assets/pages/user-view.js', '/assets/local-auth.js',
                     '/assets/cloud_public_catalog_html.html', '/user-view', '/users/1', '/api/individuals/1', '/images/1'):
            assert client.get(path).status_code == 404
        verifier.verify.assert_not_called()
        accounts.resolve_identity.assert_not_called()


def test_missing_dispute_migration_prevents_new_runtime_startup(environment, monkeypatch, dispute_schema_boundary):
    accounts, verifier = Mock(), Mock()
    monkeypatch.setattr(api, 'PostgresAccounts', Mock(return_value=accounts))
    monkeypatch.setattr(api, 'IdentityPlatformIdentity', Mock(return_value=verifier))
    dispute_schema_boundary.side_effect = ValueError('private database detail: migration missing')
    with pytest.raises(RuntimeError, match='database initialization check failed') as error:
        with TestClient(runtime.application()):
            pytest.fail('The migration must be verified before serving')
    assert 'private database detail' not in str(error.value)
    verifier.close.assert_called_once()
    runtime.CloudStorage.return_value.close.assert_called_once()


def test_dispute_schema_regression_fails_readiness_without_leaking_details(environment, monkeypatch, dispute_schema_boundary):
    accounts, verifier = Mock(), Mock()
    monkeypatch.setattr(api, 'PostgresAccounts', Mock(return_value=accounts))
    monkeypatch.setattr(api, 'IdentityPlatformIdentity', Mock(return_value=verifier))
    dispute_schema_boundary.side_effect = [None, ValueError('private checksum mismatch')]
    with TestClient(runtime.application()) as client:
        assert client.get('/health').status_code == 200
        response = client.get('/ready')
        assert response.status_code == 503 and response.json() == {'status': 'unavailable'}
        assert 'private' not in response.text


def test_private_favorites_and_visibility_wiring(environment, monkeypatch):
    accounts, verifier = Mock(), Mock()
    monkeypatch.setattr(api, 'PostgresAccounts', Mock(return_value=accounts))
    monkeypatch.setattr(api, 'IdentityPlatformIdentity', Mock(return_value=verifier))
    app = runtime.application()
    with TestClient(app) as client:
        for path in ('/api/auth/favorites', '/api/auth/favorites/1', '/api/auth/profile/visibility'):
            assert client.get(path).status_code == 401
        for path in ('/api/auth/favorites/1', '/api/auth/profile/visibility'):
            assert client.put(path, json={}).status_code == 401
        for asset in ('cloud-account-favorites.js', 'cloud-account-visibility.js'):
            result = client.get('/assets/' + asset)
            assert result.status_code == 200 and result.headers['cache-control'] == 'public, no-cache, max-age=0, must-revalidate'
        for path in ('/api/public/favorites', '/api/users/1/favorites', '/api/public/profiles/1', '/users/1'):
            assert client.get(path).status_code == 404
    verifier.verify.assert_not_called()


@pytest.mark.parametrize('cloud', [False, True])
def test_https_adapter_is_only_installed_on_cloud_run(monkeypatch, cloud):
    app=Mock()
    monkeypatch.setattr(runtime,'application',lambda:app)
    run=Mock();monkeypatch.setattr(runtime.uvicorn,'run',run)
    monkeypatch.delenv('K_SERVICE',raising=False)
    if cloud:monkeypatch.setenv('K_SERVICE','ygc-staging')
    runtime.main()
    served=run.call_args.args[0]
    assert isinstance(served,runtime.CloudRunHTTPS) if cloud else served is app


def test_cloud_https_notification_origin_keeps_cross_site_rejection():
    from fastapi import FastAPI
    from ygc.cloud_notification_routes import notification_router
    from ygc.identity_platform import VerifiedIdentity
    verifier,service=Mock(),Mock()
    verifier.verify.return_value=VerifiedIdentity('issuer','subject','',True)
    verifier.accounts.resolve_identity.return_value={'app_user_id':'canonical'}
    service.mark_read.return_value={'id':'4','is_read':True,'read_at':'2026-10-11','unread_count':'0'}
    app=FastAPI();app.include_router(notification_router(verifier,service))
    headers={'Authorization':'Bearer synthetic','Origin':'https://ygc.example'}
    # Reproduce the TLS-termination mismatch on the unadapted HTTP socket.
    with TestClient(app,base_url='http://ygc.example') as client:
        assert client.post('/api/auth/notifications/4/read',json={},headers=headers).status_code==403
    service.mark_read.assert_not_called()
    with TestClient(runtime.CloudRunHTTPS(app),base_url='http://ygc.example') as client:
        assert client.post('/api/auth/notifications/4/read',json={},headers=headers).status_code==200
        service.mark_read.assert_called_once_with('canonical',4)
        for changed in ({'Origin':'https://attacker.example'}, {'Origin':'http://ygc.example'},
                        {'Sec-Fetch-Site':'cross-site'},
                        {'Origin':'https://attacker.example','X-Forwarded-Host':'attacker.example'}):
            assert client.post('/api/auth/notifications/4/read',json={},headers=headers|changed).status_code==403
        assert service.mark_read.call_count==1
