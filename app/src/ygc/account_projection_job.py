"""Bounded Accounts-to-Chronicle worker for Cloud Run Jobs.

Uses the existing transactional outbox; never creates accounts, initializes
schema or starts HTTP/job threads. Log output contains counts only.
"""
import argparse
import json
import os
import re
import sys

from ygc.db.postgres import PostgresSettings, connect
from ygc.db.postgres_accounts import PostgresAccounts


def settings_from_environment():
    if os.environ.get('YGC_PLATFORM_TARGET') != 'gcp' or os.environ.get('YGC_DATABASE_BACKEND') != 'postgres':
        raise ValueError('Explicit GCP/PostgreSQL configuration is required.')
    if os.environ.get('K_SERVICE') or os.environ.get('CLOUD_RUN_TASK_COUNT', '1') != '1':
        raise ValueError('Use a single-task job, not a Web service.')
    project = os.environ.get('YGC_GCP_PROJECT_ID', '')
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', project):
        raise ValueError('A valid project is required.')
    settings = PostgresSettings.from_environment()
    if settings.host.startswith('/cloudsql/') and not settings.host.startswith('/cloudsql/' + project + ':'):
        raise ValueError('Cloud SQL project does not match.')
    return settings


def run(settings, *, limit=100):
    processed = PostgresAccounts(settings).drain_projection(limit=limit)
    with connect(settings, 'accounts') as con:
        pending = con.execute('SELECT COUNT(*) AS n FROM account_projection_outbox WHERE delivered_at IS NULL').fetchone()['n']
    return {'status': 'ok', 'processed': processed, 'pending': pending}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 10000:
        parser.error('--limit must be between 1 and 10000')
    try:
        result = run(settings_from_environment(), limit=args.limit)
    except Exception:
        # Failed/partially committed batches remain retryable. No PII or driver errors.
        print(json.dumps({'status': 'failed'}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
