"""Install the application with repository-pinned runtime and build dependencies."""
import argparse
from importlib.metadata import version
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[1] / 'app'
PIP_VERSION = '26.2.1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', action='store_true', help='Install runtime dependencies only')
    parser.add_argument('--browser', action='store_true', help='Include Playwright browser test dependencies')
    parser.add_argument('--postgres', action='store_true', help='Include PostgreSQL connection and migration tools')
    parser.add_argument('--identity', action='store_true', help='Include Identity Platform server verification')
    parser.add_argument('--storage', action='store_true', help='Include Cloud Storage adapter')
    args = parser.parse_args()
    if args.runtime and args.browser:
        parser.error('--runtime and --browser cannot be combined')
    if version('pip') != PIP_VERSION:
        subprocess.run([sys.executable, '-m', 'pip', 'install', f'pip=={PIP_VERSION}'], check=True)
    groups = [] if args.runtime else ['dev']
    if args.browser:
        groups.append('browser')
    if args.postgres:
        groups.append('postgres')
    if args.identity:
        groups.append('identity')
    if args.storage:
        groups.append('storage')
    extras = '[' + ','.join(groups) + ']' if groups else ''
    subprocess.run([sys.executable, '-m', 'pip', 'install',
                    '--constraint', str(APP / 'constraints.txt'),
                    '--build-constraint', str(APP / 'constraints.txt'),
                    '-e', str(APP) + extras], check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)


if __name__ == '__main__':
    main()
