"""Run repository checks with disposable storage, from any working directory."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def isolated_environment(directory):
    env = os.environ.copy()
    # Do not inherit local credentials, cloud switches or storage overrides.
    for key in list(env):
        if key.startswith('YGC_') or key in ('REVERB_API_TOKEN', 'K_SERVICE', 'CLOUD_RUN_JOB'):
            del env[key]
    env.update(YGC_DATA_DIR=str(directory), YGC_DB_PATH=str(directory / 'chronicle.db'),
               YGC_ACCOUNTS_DB_PATH=str(directory / 'accounts.sqlite'),
               YGC_LOG_DIR=str(directory / 'logs'), YGC_IDENTITY_BACKEND='prototype',
               PYTHONPATH=os.pathsep.join(filter(None, [str(ROOT / 'app/src'), env.get('PYTHONPATH')])) )
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default='node', help='Node.js executable (default: node on PATH)')
    parser.add_argument('--browser', action='store_true', help='Also run Chromium UI checks; requires .[browser] and installed Chromium')
    parser.add_argument('--browser-executable', help='Optional Chrome/Chromium executable')
    parser.add_argument('--browser-artifacts', type=Path, help='Keep screenshots and traces of failed disposable browser checks here')
    pg = parser.add_mutually_exclusive_group()
    pg.add_argument('--postgres-bin', type=Path, help='Run PostgreSQL checks with a temporary local cluster')
    pg.add_argument('--postgres-port', type=int, help='Run PostgreSQL checks against the loopback CI test service')
    args = parser.parse_args()
    node = shutil.which(args.node)
    if not node:
        parser.error('Node.js is required. Install Node.js or specify --node PATH.')
    with tempfile.TemporaryDirectory(prefix='ygc-tests-') as temporary:
        env = isolated_environment(Path(temporary))
        checks = [('Python', [sys.executable, '-m', 'pytest', 'app/tests', '-q']),
                  ('JavaScript', [node, '--test', *map(str, sorted((ROOT / 'app/tests').glob('test_*.cjs')))])]
        if args.browser:
            if args.browser_artifacts:
                env['YGC_BROWSER_ARTIFACTS'] = str(args.browser_artifacts.resolve())
            if args.browser_executable:
                env['YGC_BROWSER_EXECUTABLE'] = args.browser_executable
            checks.append(('Browser', [sys.executable, str(ROOT / 'app/tests/run_browser_checks.py')]))
        failures = []
        if args.postgres_bin or args.postgres_port:
            option = ['--postgres-bin', str(args.postgres_bin.resolve())] if args.postgres_bin else ['--port', str(args.postgres_port)]
            checks.append(('PostgreSQL', [sys.executable, str(ROOT / 'app/tests/run_postgres_checks.py'), *option]))
        for label, command in checks:
            print(f'\nRunning {label} checks with temporary storage', flush=True)
            code = subprocess.run(command, cwd=ROOT, env=env).returncode
            if code:
                failures.append(f'{label} (exit {code})')
        if failures:
            print('\nFailed: ' + ', '.join(failures), file=sys.stderr)
            return 1
    print('\nAll requested checks passed. Temporary storage removed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
