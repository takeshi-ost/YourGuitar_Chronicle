"""Configuration/artifact checks without a real DB or cloud credentials."""
import hashlib
import json
import pytest
from ygc.db.postgres import ARTIFACTS, TARGETS, PostgresSettings, schema


def test_artifacts_cover_four_stores():
    manifest = json.loads((ARTIFACTS / 'manifest.json').read_text())
    assert set(manifest) == set(TARGETS)
    for target in TARGETS:
        content, expected = schema(target)
        assert expected['tables']
        assert hashlib.sha256(content.encode()).hexdigest() == expected['sha256']
        assert 'CREATE TABLE' in content


def test_settings_password_not_in_repr(monkeypatch):
    monkeypatch.setenv('YGC_POSTGRES_HOST', '127.0.0.1')
    monkeypatch.setenv('YGC_POSTGRES_USER', 'ygc_app')
    settings = PostgresSettings.from_environment('private-test-password')
    assert 'private-test-password' not in repr(settings)
    assert settings.database('accounts') == 'ygc_accounts'
    with pytest.raises(ValueError):
        settings.database('../unrecognized')


@pytest.mark.parametrize('key,value', [('YGC_POSTGRES_HOST', 'external.example'),
                                      ('YGC_POSTGRES_PORT', '0'),
                                      ('YGC_POSTGRES_PORT', '65536'),
                                      ('YGC_POSTGRES_PREFIX', '../unsafe')])
def test_invalid_configuration(monkeypatch, key, value):
    monkeypatch.setenv('YGC_POSTGRES_HOST', 'localhost')
    monkeypatch.setenv('YGC_POSTGRES_USER', 'ygc_app')
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        PostgresSettings.from_environment('test-only')


@pytest.mark.parametrize('prompt', [False, True])
def test_migrate_cli_calls_migration_after_loading_credentials(monkeypatch, capsys, prompt):
    from unittest.mock import Mock
    from ygc.db import postgres
    settings = PostgresSettings('localhost', 'owner', 'private-test-password')
    load = Mock(return_value=settings)
    migrate = Mock(return_value=[2])
    monkeypatch.setattr(postgres.PostgresSettings, 'from_environment', load)
    monkeypatch.setattr(postgres, 'migrate', migrate)
    status = Mock(side_effect=AssertionError('migrate must not merely return status'))
    monkeypatch.setattr(postgres, 'status', status)
    monkeypatch.setattr('getpass.getpass', Mock(return_value='private-test-password'))
    assert postgres.main(['migrate', '--target', 'accounts', *(['--password-prompt'] if prompt else [])]) == 0
    load.assert_called_once_with('private-test-password' if prompt else None)
    migrate.assert_called_once_with(settings, 'accounts', 'ygc_app')
    assert json.loads(capsys.readouterr().out) == {'target': 'accounts', 'applied': [2]}


def test_initialize_cli_reads_password_once_and_does_not_print_it(monkeypatch, capsys):
    from unittest.mock import Mock
    from ygc.db import postgres
    settings = PostgresSettings('localhost', 'owner', 'private-test-password')
    monkeypatch.setattr(postgres.PostgresSettings, 'from_environment', Mock(return_value=settings))
    initialize = Mock(return_value=[{'target': 'accounts', 'version': 2}])
    monkeypatch.setattr(postgres, 'initialize', initialize)
    prompt = Mock(return_value='private-test-password')
    monkeypatch.setattr('getpass.getpass', prompt)
    assert postgres.main(['initialize', '--password-prompt']) == 0
    initialize.assert_called_once_with(settings, 'ygc_app')
    prompt.assert_called_once()
    output = capsys.readouterr().out
    assert 'private-test-password' not in output
    assert json.loads(output)['databases'][0]['version'] == 2


def test_cli_error_does_not_echo_password(monkeypatch, capsys):
    from ygc.db import postgres
    def reject(*args):
        raise ValueError('private-test-password')
    monkeypatch.setattr(postgres.PostgresSettings, 'from_environment', reject)
    assert postgres.main(['migrate', '--target', 'accounts']) == 1
    assert 'private-test-password' not in capsys.readouterr().out


@pytest.mark.parametrize('args', [['migrate'], ['status'], ['bootstrap'], ['initialize','--target','accounts']])
def test_cli_rejects_incomplete_or_ambiguous_scope(args):
    from ygc.db import postgres
    with pytest.raises(SystemExit) as error:
        postgres.main(args)
    assert error.value.code == 2


def test_initialize_validates_all_revisions_before_writes(monkeypatch):
    from unittest.mock import Mock
    from ygc.db import postgres
    def check(target):
        if target == 'authentication':
            raise ValueError('Broken packaged migration')
    monkeypatch.setattr(postgres, 'schema_versions', check)
    bootstrap = Mock()
    monkeypatch.setattr(postgres, 'bootstrap', bootstrap)
    with pytest.raises(ValueError):
        postgres.initialize(object())
    bootstrap.assert_not_called()
