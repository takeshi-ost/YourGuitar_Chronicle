from unittest.mock import Mock
import pytest
pytest.importorskip('psycopg')
from fastapi.testclient import TestClient
from ygc import cloud_account_runtime as runtime
from ygc import cloud_account_api as api


@pytest.fixture
def environment(monkeypatch):
    values = {'YGC_PLATFORM_TARGET': 'gcp', 'YGC_DATABASE_BACKEND': 'postgres',
              'YGC_IDENTITY_BACKEND': 'identity_platform', 'YGC_IDENTITY_PROJECT_ID': 'test-project',
              'YGC_POSTGRES_HOST': '/cloudsql/test-project:asia-northeast1:db',
              'YGC_POSTGRES_USER': 'ygc_app', 'YGC_POSTGRES_PASSWORD': 'private-password',
              'YGC_FIREBASE_API_KEY': 'public-key',
              'YGC_FIREBASE_AUTH_DOMAIN': 'test-project.firebaseapp.com'}
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
        assert '/assets/cloud-console-page.js' in shell.text
        assert client.get('/assets/cloud-console-page.js').status_code == 200
        assert client.get('/assets/cloud-console.css').status_code == 200
        assert client.get('/assets/pages/console.js').status_code == 404
        assert client.get('/assets/cloud_console_html.html').status_code == 404
        verifier.verify.assert_not_called()
        accounts.resolve_identity.assert_not_called()
