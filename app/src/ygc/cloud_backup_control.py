"""Persistent manual-save requests; fixed IAM Job, no browser-selected cloud resources."""
from datetime import datetime, timezone, timedelta
import json
import re
import uuid
from ygc.cloud_backup_job import KIND
from ygc.db.postgres import TARGETS

REQUEST_KIND = 'db_backup_request_v1'
WINDOW = timedelta(minutes=10)


class BackupBusy(Exception):
    pass


def request_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Use a canonical request UUID.')
    return value


class BackupJobClient:
    def __init__(self, project, region, *, session=None):
        if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', project) or not re.fullmatch(r'[a-z]+-[a-z]+[0-9]', region):
            raise ValueError('Explicit backup project and region required.')
        self.project = project
        self.prefix = f'projects/{project}/locations/{region}'
        self.job = self.prefix + '/jobs/ygc-staging-db-backup'
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
            session = AuthorizedSession(credentials)
        self.session = session

    def start(self, target, token):
        if target not in TARGETS:
            raise ValueError('Unknown target.')
        request_id(token)
        response = self.session.post('https://run.googleapis.com/v2/' + self.job + ':run',
            json={'overrides': {'containerOverrides': [{
                'args': ['-m', 'ygc.cloud_backup_job', '--confirm-project=' + self.project, '--target=' + target],
                'env': [{'name': 'YGC_BACKUP_REQUEST_ID', 'value': token}]}]}}, timeout=10)
        response.raise_for_status()
        operation = response.json()['name']
        self._operation(operation)
        return operation

    def _operation(self, name):
        if not isinstance(name, str) or not re.fullmatch(re.escape(self.prefix) + r'/operations/[A-Za-z0-9_-]+', name):
            raise ValueError('Unexpected operation resource.')

    def status(self, operation):
        self._operation(operation)
        response = self.session.get('https://run.googleapis.com/v2/' + operation, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('error'):return 'failed'
        if not data.get('done'):return 'running'
        execution = data.get('response', {}).get('name', '')
        if not re.fullmatch(re.escape(self.job) + r'/executions/[A-Za-z0-9_-]+', execution):
            raise ValueError('Unexpected execution resource.')
        response = self.session.get('https://run.googleapis.com/v2/' + execution, timeout=10)
        response.raise_for_status()
        row = response.json()
        if not row.get('completionTime'):return 'running'
        return 'finished' if row.get('succeededCount') == 1 else 'failed'

    def close(self):
        self.session.close()


def _encoded(record):
    return json.dumps(record, separators=(',', ':'))


def _find(con, kind, field, value):
    return con.execute("""SELECT id,reason FROM events WHERE
        CASE WHEN reason LIKE %s THEN reason::jsonb ELSE NULL END ->>%s=%s
        ORDER BY id DESC LIMIT 1""", ('{"kind":"' + kind + '",%', field, value)).fetchone()


def _public(record):
    return {key: record[key] for key in ('request_id', 'target', 'state', 'created_at')}


class BackupControl:
    def __init__(self, operations, client):
        self.operations, self.client = operations, client

    def start(self, actor, target, token):
        if target not in TARGETS:
            raise ValueError('Unknown target.')
        request_id(token)
        with self.operations.access('admin_write', actor) as (con, mode, account):
            existing = _find(con, REQUEST_KIND, 'request_id', token)
            if existing:
                record = json.loads(existing['reason'])
                if record['target'] != target or record['actor'] != str(actor):
                    raise ValueError('Request does not match.')
                return _public(record)
            previous = _find(con, REQUEST_KIND, 'target', target)
            now = datetime.now(timezone.utc)
            if previous:
                row = json.loads(previous['reason'])
                if row['state'] in ('starting', 'running', 'unknown') and now - datetime.fromisoformat(row['created_at']) < WINDOW:
                    raise BackupBusy()
            record = {'kind': REQUEST_KIND, 'request_id': token, 'target': target,
                      'actor': str(actor), 'state': 'starting', 'created_at': now.isoformat()}
            event = con.execute('INSERT INTO events(occurred_at,mode,reason) VALUES(%s,%s,%s) RETURNING id',
                (record['created_at'], mode['mode'], _encoded(record))).fetchone()['id']
            # Commit the intent before a non-idempotent provider call. Never launch twice for this UUID.
            con.commit()
            try:
                record['operation'] = self.client.start(target, token)
                record['state'] = 'running'
            except Exception:
                # Provider timeout can mean an execution exists. Do not retry automatically.
                record['state'] = 'unknown'
            con.execute('UPDATE events SET reason=%s WHERE id=%s', (_encoded(record), event))
            con.commit()
            return _public(record)

    def status(self, actor, target):
        if target not in TARGETS:
            raise ValueError('Unknown target.')
        with self.operations.access('admin_write', actor) as (con, mode, account):
            event = _find(con, REQUEST_KIND, 'target', target)
            if not event:
                return {'target': target, 'state': 'idle'}
            record = json.loads(event['reason'])
            if record['state'] != 'succeeded':
                saved = _find(con, KIND, 'request_id', record['request_id'])
                if saved:
                    record['state'] = 'succeeded'
                elif record['state'] in ('starting', 'running', 'unknown') and record.get('operation'):
                    try:
                        state = self.client.status(record['operation'])
                        if state in ('failed', 'finished'):
                            # Job completion without the committed save record is not a successful backup.
                            record['state'] = 'failed'
                    except Exception:
                        pass
                if datetime.now(timezone.utc) - datetime.fromisoformat(record['created_at']) >= WINDOW and record['state'] in ('starting', 'running'):
                    record['state'] = 'unknown'
                con.execute('UPDATE events SET reason=%s WHERE id=%s', (_encoded(record), event['id']))
            result = _public(record)
            result['retry_allowed'] = record['state'] not in ('starting', 'running', 'unknown') or datetime.now(timezone.utc) - datetime.fromisoformat(record['created_at']) >= WINDOW
            return result
