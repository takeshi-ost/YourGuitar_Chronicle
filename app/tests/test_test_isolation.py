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


def test_pytest_cleans_storage_on_success_failure_and_interrupt(tmp_path):
    import json
    plugin = tmp_path / 'cleanup_probe.py'
    plugin.write_text('''import json, os
from pathlib import Path
import pytest

def pytest_sessionstart(session):
    root = Path(os.environ['YGC_DATA_DIR'])
    Path(os.environ['CLEANUP_RECORD']).write_text(json.dumps({
        'root':str(root), 'base':session.config.option.basetemp,
        'cache':session.config.getini('cache_dir')}))

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    mode = os.environ['CLEANUP_MODE']
    if mode == 'failure':
        pytest.fail('intentional cleanup probe')
    if mode == 'interrupt':
        raise KeyboardInterrupt()
''')
    root = Path(__file__).resolve().parents[2]
    for mode, expected_code in [('success', 0), ('failure', 1), ('interrupt', 2)]:
        record = tmp_path / (mode + '.json')
        env = dict(os.environ, CLEANUP_MODE=mode, CLEANUP_RECORD=str(record),
                   PYTHONPATH=os.pathsep.join([str(tmp_path), str(root / 'app/src')]))
        result = subprocess.run([sys.executable, '-m', 'pytest', '-p', 'cleanup_probe',
                                 'app/tests/test_ui_assets.py', '-q'], cwd=root, env=env,
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == expected_code, result.stdout + result.stderr
        paths = json.loads(record.read_text())
        for name in ('base', 'cache'):
            assert Path(paths[name]).is_relative_to(Path(paths['root']))
        assert not Path(paths['root']).exists(), paths


def test_external_basetemp_is_rejected_without_deleting_files(tmp_path):
    target = tmp_path / 'do-not-delete'
    target.mkdir()
    sentinel = target / 'original.txt'
    sentinel.write_text('keep this file')
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, '-m', 'pytest', 'app/tests/test_ui_assets.py',
                             '--basetemp', str(target), '-q'], cwd=root,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 4, result.stdout + result.stderr
    assert 'do not supply --basetemp' in result.stderr
    assert sentinel.read_text() == 'keep this file'
