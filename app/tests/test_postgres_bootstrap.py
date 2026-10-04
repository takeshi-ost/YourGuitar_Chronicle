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
