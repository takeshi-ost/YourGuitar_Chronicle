# Establish disposable paths BEFORE importing any application module.
import os
import tempfile
import atexit
from pathlib import Path

_test_storage = tempfile.TemporaryDirectory(prefix='ygc-pytest-')
atexit.register(_test_storage.cleanup)
_test_root = Path(_test_storage.name)
for _key in list(os.environ):
    if _key.startswith('YGC_') or _key in ('REVERB_API_TOKEN', 'K_SERVICE', 'CLOUD_RUN_JOB'):
        del os.environ[_key]
os.environ.update(
    YGC_DATA_DIR=str(_test_root), YGC_DB_PATH=str(_test_root / 'chronicle.db'),
    YGC_ACCOUNTS_DB_PATH=str(_test_root / 'accounts.sqlite'),
    YGC_LOG_DIR=str(_test_root / 'logs'), YGC_IDENTITY_BACKEND='prototype',
)

import pytest

from ygc.db.repository import utcnow


@pytest.fixture
def legacy_marketplace_row():
    """Explicitly model a pre-Evidence writer without using today's write path."""
    def attach(repo, result, claim, provenance):
        observation_id, created = repo.upsert_observation({
            **claim, **provenance, 'individual_id': result['individual_id'],
            'observed_at': provenance.get('observed_at') or utcnow(),
            'created_at': provenance.get('created_at') or utcnow(),
        })
        assert created
        with repo.connect() as con:
            con.execute('UPDATE claims SET observation_id=? WHERE id=?',
                        (observation_id, result['claim_id']))
            con.execute('UPDATE claim_source_evidence SET legacy_observation_id=? WHERE claim_id=?',
                        (observation_id, result['claim_id']))
        return observation_id
    return attach


@pytest.fixture(autouse=True)
def isolated_runtime_storage(tmp_path, monkeypatch):
    """Each test gets fresh default paths; feature fixtures may override them."""
    from ygc import config
    for name, value in {
        'DATA_DIR': tmp_path,
        'DB_PATH': tmp_path / 'chronicle.db',
        'ACCOUNTS_DB_PATH': tmp_path / 'accounts.sqlite',
        'LOG_DIR': tmp_path / 'logs',
    }.items():
        monkeypatch.setattr(config, name, value)
        monkeypatch.setenv('YGC_' + name, str(value))
