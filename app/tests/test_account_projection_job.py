import json
from unittest.mock import Mock, MagicMock
import pytest
pytest.importorskip('psycopg')
from ygc import account_projection_job as job


@pytest.fixture
def configured(monkeypatch):
    for key in ('K_SERVICE', 'CLOUD_RUN_TASK_COUNT'):
        monkeypatch.delenv(key, raising=False)
    for key, value in {'YGC_PLATFORM_TARGET': 'gcp', 'YGC_DATABASE_BACKEND': 'postgres',
        'YGC_GCP_PROJECT_ID': 'test-project', 'YGC_POSTGRES_HOST': '/cloudsql/test-project:region:db',
        'YGC_POSTGRES_USER': 'ygc_app', 'YGC_POSTGRES_PASSWORD': 'private-password'}.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize('key,value', [('YGC_PLATFORM_TARGET', 'local'), ('YGC_DATABASE_BACKEND', 'sqlite'),
    ('YGC_GCP_PROJECT_ID', ''), ('K_SERVICE', 'web'), ('CLOUD_RUN_TASK_COUNT', '2'),
    ('YGC_POSTGRES_HOST', '/cloudsql/other-project:region:db')])
def test_invalid_configuration_never_runs(configured, monkeypatch, key, value, capsys):
    run = Mock()
    monkeypatch.setattr(job, 'run', run)
    monkeypatch.setenv(key, value)
    assert job.main([]) == 1
    run.assert_not_called()
    assert 'private-password' not in capsys.readouterr().err


def test_failure_is_retryable_and_does_not_leak(configured, monkeypatch, capsys):
    run = Mock(side_effect=RuntimeError('private-password profile-name token'))
    monkeypatch.setattr(job, 'run', run)
    assert job.main([]) == 1
    output = capsys.readouterr()
    assert output.out == ''
    assert json.loads(output.err) == {'status': 'failed'}
    run.assert_called_once()


def test_bounded_batch_reports_counts_only(monkeypatch):
    store = Mock()
    store.drain_projection.return_value = 2
    monkeypatch.setattr(job, 'PostgresAccounts', Mock(return_value=store))
    con = MagicMock()
    con.execute.return_value.fetchone.return_value = {'n': 3}
    context = MagicMock()
    context.__enter__.return_value = con
    monkeypatch.setattr(job, 'connect', Mock(return_value=context))
    assert job.run(object(), limit=2) == {'status': 'ok', 'processed': 2, 'pending': 3}
    store.drain_projection.assert_called_once_with(limit=2)


@pytest.mark.parametrize('limit', ['0', '10001'])
def test_invalid_limit_never_connects(monkeypatch, limit):
    run = Mock()
    monkeypatch.setattr(job, 'run', run)
    with pytest.raises(SystemExit):
        job.main(['--limit', limit])
    run.assert_not_called()
