"""Check that ordinary pytest ignores inherited production storage settings."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def test_direct_pytest_does_not_touch_inherited_data(tmp_path):
    original = tmp_path / 'original'
    original.mkdir()
    sentinels = {'chronicle.db':b'original guitar data', 'accounts.sqlite':b'original accounts',
                 'reference.png':b'original image'}
    for name, data in sentinels.items():
        (original / name).write_bytes(data)
    env = dict(os.environ, YGC_DATA_DIR=str(original), YGC_DB_PATH=str(original / 'chronicle.db'),
               YGC_ACCOUNTS_DB_PATH=str(original / 'accounts.sqlite'), YGC_LOG_DIR=str(original / 'logs'))
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, '-m', 'pytest', 'app/tests/test_ui_assets.py', '-q'],
                            cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(p.name for p in original.iterdir()) == sorted(sentinels)
    for name, data in sentinels.items():
        assert (original / name).read_bytes() == data


def test_unified_runner_replaces_storage_and_removes_credentials(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2] / 'scripts/run_tests.py'
    spec = importlib.util.spec_from_file_location('test_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setenv('YGC_DB_PATH', '/original/database')
    monkeypatch.setenv('REVERB_API_TOKEN', 'do-not-use')
    monkeypatch.setenv('K_SERVICE', 'production')
    env = runner.isolated_environment(tmp_path)
    assert env['YGC_DB_PATH'] == str(tmp_path / 'chronicle.db')
    assert env['YGC_ACCOUNTS_DB_PATH'] == str(tmp_path / 'accounts.sqlite')
    assert 'REVERB_API_TOKEN' not in env
    assert 'K_SERVICE' not in env
