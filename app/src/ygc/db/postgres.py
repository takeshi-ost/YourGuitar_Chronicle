"""Explicit PostgreSQL connections and versioned bootstrap, separate from WebUI.

Runtime users never initialize schema. No SQLite compatibility fallback exists.
Cloud Run uses its Cloud SQL Unix socket; local testing uses a loopback proxy.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import argparse
import hashlib
import json
import os
import copy
from pathlib import Path

ARTIFACTS = Path(__file__).with_name('postgres')
TARGETS = ('chronicle', 'accounts', 'operations', 'authentication')


@dataclass(frozen=True)
class PostgresSettings:
    host: str
    user: str
    password: str = field(repr=False)
    port: int = 5432
    prefix: str = 'ygc_'

    @classmethod
    def from_environment(cls, password=None):
        host = os.environ.get('YGC_POSTGRES_HOST', '')
        user = os.environ.get('YGC_POSTGRES_USER', '')
        password = password if password is not None else os.environ.get('YGC_POSTGRES_PASSWORD', '')
        if not host or not user or not password:
            raise ValueError('Set YGC_POSTGRES_HOST, YGC_POSTGRES_USER and YGC_POSTGRES_PASSWORD.')
        if host not in ('127.0.0.1', 'localhost', '::1') and not host.startswith('/cloudsql/'):
            raise ValueError('Use a loopback Cloud SQL proxy or a /cloudsql/ Unix socket.')
        prefix = os.environ.get('YGC_POSTGRES_PREFIX', 'ygc_')
        if not prefix or not prefix.replace('_', '').isalnum():
            raise ValueError('Invalid database prefix.')
        port = int(os.environ.get('YGC_POSTGRES_PORT', '5432'))
        if not 1 <= port <= 65535:
            raise ValueError('Invalid PostgreSQL port.')
        return cls(host, user, password, port, prefix)

    def database(self, target):
        if target not in TARGETS:
            raise ValueError('Unknown database target.')
        return self.prefix + target


@contextmanager
def connect(settings, target):
    import psycopg
    from psycopg.rows import dict_row
    # Separate parameters, never a password-bearing DSN in errors or logs.
    with psycopg.connect(host=settings.host, port=settings.port,
                         dbname=settings.database(target), user=settings.user,
                         password=settings.password, connect_timeout=10,
                         application_name='ygc-postgres', row_factory=dict_row) as con:
        con.execute('SET statement_timeout = 60000')
        yield con


def schema(target):
    if target not in TARGETS:
        raise ValueError('Unknown database target.')
    manifest = json.loads((ARTIFACTS/'manifest.json').read_text())
    content = (ARTIFACTS/(target+'_001.sql')).read_text()
    if hashlib.sha256(content.encode()).hexdigest() != manifest[target]['sha256']:
        raise ValueError('PostgreSQL schema checksum mismatch.')
    return content, manifest[target]


def bootstrap(settings, target, runtime_user='ygc_app'):
    """Initialize one empty store atomically, or verify its recorded version."""
    from psycopg import sql
    content, expected = schema(target)
    with connect(settings, target) as con:
        if int(con.execute('SHOW server_version_num').fetchone()['server_version_num']) < 180000:
            raise ValueError('The bootstrap requires PostgreSQL 18 or later.')
        if con.execute('SELECT current_user AS name').fetchone()['name'] == runtime_user:
            raise ValueError('Use a separate schema owner, not the application user.')
        con.execute('SELECT pg_advisory_xact_lock(79432001)')
        names = {r['tablename'] for r in con.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
        if 'ygc_schema_version' in names:
            version = con.execute('SELECT version,checksum FROM ygc_schema_version WHERE id=1').fetchone()
            recorded = recorded_schema(target, version)
            validate_schema(con, recorded)
            return False
        if names:
            raise ValueError('Refusing bootstrap of an existing, unversioned database.')
        con.execute(content, prepare=False)
        con.execute('CREATE TABLE ygc_schema_version (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, checksum TEXT NOT NULL)')
        con.execute('INSERT INTO ygc_schema_version VALUES (1,1,%s)', (expected['sha256'],))
        # No public schema creation; application data permissions only.
        con.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        con.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(settings.database(target)), sql.Identifier(runtime_user)))
        con.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(runtime_user)))
        for table in expected['tables']:
            con.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}').format(sql.Identifier(table), sql.Identifier(runtime_user)))
        con.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(runtime_user)))
        con.execute(sql.SQL('GRANT SELECT ON TABLE ygc_schema_version TO {}').format(sql.Identifier(runtime_user)))
        validate_schema(con, expected)
    return True


def validate_schema(con, expected):
    actual = {}
    for row in con.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position"):
        actual.setdefault(row['table_name'], []).append(row['column_name'])
    actual.pop('ygc_schema_version', None)
    if actual != expected['tables']:
        raise ValueError('PostgreSQL table/column structure differs from the recorded schema.')


def schema_versions(target):
    """Known immutable revisions; never infer a migration from runtime SQLite."""
    _, base = schema(target)
    expected = copy.deepcopy(base)
    result = [(1, expected['sha256'], copy.deepcopy(expected), '')]
    path = ARTIFACTS / 'migration_manifest.json'
    migrations = json.loads(path.read_text()) if path.exists() else {}
    for revision in migrations.get(target, []):
        if revision['version'] != result[-1][0] + 1:
            raise ValueError('Non-consecutive schema revisions.')
        content = (ARTIFACTS / revision['file']).read_text()
        digest = hashlib.sha256(content.encode()).hexdigest()
        if digest != revision['sha256']:
            raise ValueError('Migration checksum mismatch.')
        for table, columns in revision.get('append_columns', {}).items():
            expected['tables'][table].extend(columns)
        expected['tables'].update(revision.get('tables', {}))
        checksum = hashlib.sha256((result[-1][1] + digest).encode()).hexdigest()
        result.append((revision['version'], checksum, copy.deepcopy(expected), content))
    return result


def recorded_schema(target, row):
    for version, checksum, expected, _ in schema_versions(target):
        if row and row['version'] == version and row['checksum'] == checksum:
            return expected
    raise ValueError('Unknown schema version/checksum; an explicit migration is required.')


def migrate(settings, target, runtime_user='ygc_app'):
    """Apply reviewed revisions atomically to an already bootstrapped store."""
    from psycopg import sql
    revisions = schema_versions(target)
    with connect(settings, target) as con:
        if con.execute('SELECT current_user AS name').fetchone()['name'] == runtime_user:
            raise ValueError('Use a separate schema owner, not the application user.')
        con.execute('SELECT pg_advisory_xact_lock(79432001)')
        row = con.execute('SELECT version,checksum FROM ygc_schema_version WHERE id=1 FOR UPDATE').fetchone()
        validate_schema(con, recorded_schema(target, row))
        applied = []
        for version, checksum, expected, content in revisions:
            if version <= row['version']:
                continue
            con.execute(content, prepare=False)
            for table in expected['tables']:
                con.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}').format(sql.Identifier(table), sql.Identifier(runtime_user)))
            con.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(runtime_user)))
            con.execute('UPDATE ygc_schema_version SET version=%s,checksum=%s WHERE id=1', (version, checksum))
            validate_schema(con, expected)
            applied.append(version)
        return applied


def status(settings, target):
    with connect(settings, target) as con:
        row = con.execute('SELECT version,checksum FROM ygc_schema_version WHERE id=1').fetchone()
        expected = recorded_schema(target, row)
        validate_schema(con, expected)
        return {'target': target, 'version': row['version'], 'tables': len(expected['tables'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('status', 'bootstrap', 'migrate'))
    parser.add_argument('--target', choices=TARGETS, required=True)
    parser.add_argument('--runtime-user', default='ygc_app')
    parser.add_argument('--password-prompt', action='store_true', help='Read the DB password privately instead of from the environment')
    args = parser.parse_args()
    try:
        if args.password_prompt:
            from getpass import getpass
            password = getpass('Database password (not saved): ')
        elif args.operation == 'migrate':
            print(json.dumps({'target': args.target, 'applied': migrate(settings, args.target, args.runtime_user)}))
        else:
            password = None
        settings = PostgresSettings.from_environment(password)
        if args.operation == 'bootstrap':
            created = bootstrap(settings, args.target, args.runtime_user)
            print(json.dumps({'target': args.target, 'initialized': created}))
        else:
            print(json.dumps(status(settings, args.target)))
    except Exception as exc:
        # Connection errors can contain operational details; never echo credentials.
        print('PostgreSQL operation failed (' + type(exc).__name__ + '). Check connection, grants, schema and configuration.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
