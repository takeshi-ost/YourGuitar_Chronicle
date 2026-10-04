"""Integration checks against disposable PostgreSQL 18 databases only.

Use --postgres-bin to launch a temporary local cluster, or --port for a CI test
service with postgres / ygc-tests-only. Never accepts a cloud host, DSN or secret.
"""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import psycopg
from psycopg import sql
from ygc.db.postgres import PostgresSettings, TARGETS, bootstrap, connect, status


@contextmanager
def server(binpath, port):
    if not binpath:
        yield port
        return
    with tempfile.TemporaryDirectory(prefix='ygc-postgres-tests-') as tmp:
        root = Path(tmp)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        subprocess.run([str(binpath/'initdb'), '-D', str(root/'data'), '-U', 'postgres', '-A', 'trust', '--no-locale', '--encoding=UTF8'], check=True, stdout=subprocess.DEVNULL)
        started = False
        try:
            subprocess.run([str(binpath/'pg_ctl'), '-D', str(root/'data'), '-l', str(root/'server.log'), '-o', '-h 127.0.0.1 -p '+str(port)+' -k '+tmp, '-w', 'start'], check=True, stdout=subprocess.DEVNULL)
            started = True
            yield port
        finally:
            if started:
                subprocess.run([str(binpath/'pg_ctl'), '-D', str(root/'data'), '-m', 'immediate', '-w', 'stop'], check=True, stdout=subprocess.DEVNULL)


def rejected(con, query, params=None):
    try:
        with con.transaction():
            con.execute(query, params)
    except psycopg.Error:
        return
    raise AssertionError('Expected database rejection: ' + query)


def initialization_checks(port):
    """Exercise the actual CLI, not just direct bootstrap/migration functions."""
    prefix = 'ygctest_init_' + uuid.uuid4().hex[:10] + '_'
    runtime = prefix + 'app'
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port, prefix)
    app = PostgresSettings('127.0.0.1', runtime, 'ygc-tests-only', port, prefix)
    env = os.environ.copy()
    env.update(YGC_POSTGRES_HOST='127.0.0.1', YGC_POSTGRES_PORT=str(port),
               YGC_POSTGRES_USER='postgres', YGC_POSTGRES_PASSWORD='ygc-tests-only',
               YGC_POSTGRES_PREFIX=prefix)
    created = []
    import json
    def command(*args):
        result = subprocess.run([sys.executable, '-m', 'ygc.db.postgres', *args],
                                env=env, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='postgres',
                        password='ygc-tests-only', autocommit=True) as admin:
        try:
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(runtime), sql.Literal('ygc-tests-only')))
            for target in TARGETS:
                name = owner.database(target)
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                created.append(name)
            # Resume after one target was committed by an earlier attempt.
            assert bootstrap(owner, 'chronicle', runtime)
            initialized = command('initialize', '--runtime-user', runtime)['databases']
            assert [row['target'] for row in initialized] == list(TARGETS)
            assert [row['version'] for row in initialized] == [2, 2, 1, 1]
            assert [row['initialized'] for row in initialized] == [False, True, True, True]
            with connect(app, 'accounts') as con:
                con.execute("INSERT INTO account_records(app_user_id,display_name,created_at,updated_at) VALUES('fixture-kept','Keep profile','now','now')")
            repeated = command('initialize', '--runtime-user', runtime)['databases']
            assert all(not row['initialized'] and not row['applied'] for row in repeated)
            with connect(app, 'accounts') as con:
                assert con.execute("SELECT display_name FROM account_records WHERE app_user_id='fixture-kept'").fetchone()['display_name'] == 'Keep profile'
            assert command('migrate', '--target', 'accounts', '--runtime-user', runtime) == {'target': 'accounts', 'applied': []}
            print('PostgreSQL CLI: initialize all stores, resume partial initialization, preserve existing data and execute migrate passed.')
        finally:
            for name in reversed(created):
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))


def run(port):
    prefix = 'ygctest_' + uuid.uuid4().hex[:12] + '_'
    runtime = prefix+'app'
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port, prefix)
    app = PostgresSettings('127.0.0.1', runtime, 'ygc-tests-only', port, prefix)
    created = []
    with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='postgres', password='ygc-tests-only', autocommit=True) as admin:
        try:
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(runtime), sql.Literal('ygc-tests-only')))
            for target in TARGETS:
                name = owner.database(target)
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                created.append(name)
                if target == 'authentication':
                    try:
                        bootstrap(owner, target, runtime + '_missing')
                    except psycopg.errors.UndefinedObject:
                        pass
                    else:
                        raise AssertionError('Missing runtime role must roll back bootstrap.')
                    with connect(owner, target) as con:
                        assert not con.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
                assert bootstrap(owner, target, runtime)
                assert not bootstrap(owner, target, runtime)
                assert status(app, target)['tables'] > 0
                try:
                    bootstrap(app, target, runtime)
                except ValueError:
                    pass
                else:
                    raise AssertionError('Runtime user must not bootstrap schema.')
                with connect(app, target) as con:
                    rejected(con, 'CREATE TABLE forbidden(id BIGINT)')
                    rejected(con, 'UPDATE ygc_schema_version SET version=2')
            with connect(app, 'operations') as con:
                assert con.execute('SELECT mode FROM settings WHERE id=1').fetchone()['mode'] == 'offline'
                assert con.execute('SELECT enabled FROM auto_crawl WHERE id=1').fetchone()['enabled'] == 0
                assert con.execute('SELECT enabled FROM review_settings WHERE id=1').fetchone()['enabled'] == 0
                assert all(row['enabled'] == 0 for row in con.execute('SELECT enabled FROM backup_schedules'))
            with connect(app, 'accounts') as con:
                con.execute("INSERT INTO account_records(id,app_user_id,display_name) VALUES (1,'test-uuid','Alice')")
                rejected(con, "UPDATE account_records SET app_user_id='other' WHERE id=1")
                rejected(con, 'DELETE FROM account_records WHERE id=1')
                rejected(con, "INSERT INTO identity_links VALUES('issuer','','subject','unknown')")
            # Repeating bootstrap cannot overwrite runtime data or reset accounts.
            assert not bootstrap(owner, 'accounts', runtime)
            with connect(app, 'accounts') as con:
                assert con.execute('SELECT display_name FROM account_records WHERE id=1').fetchone()['display_name'] == 'Alice'
            with connect(app, 'chronicle') as con:
                for user in (1, 2):
                    con.execute("INSERT INTO users(id,display_name,created_at,updated_at) VALUES (%s,%s,'2026-10-04','2026-10-04')", (user, 'User'+str(user)))
                individual = con.execute("INSERT INTO individuals(manufacturer,normalized_manufacturer,created_at,updated_at,current_owner_user_id) VALUES('Fender','fender','2026-10-04','2026-10-04',1) RETURNING id").fetchone()['id']
                claim = con.execute("INSERT INTO claims(individual_id,author_user_id,claim_type,created_at,updated_at) VALUES(%s,1,'ownership','2026-10-04','2026-10-04') RETURNING id", (individual,)).fetchone()['id']
                rejected(con, "INSERT INTO crawl_unregistered_records(source_site,source_listing_id,source_url,observed_at,reason,payload_json,created_at) VALUES('reverb','x','url','now','test','bad-json','now')")
                con.execute("INSERT INTO ownership_disputes(individual_id,owner_id,locked_owner_id,created_at,updated_at) VALUES(%s,1,1,'now','now')", (individual,))
                rejected(con, 'UPDATE claims SET verification_status=\'negative\' WHERE id=%s', (claim,))
                rejected(con, 'DELETE FROM claims WHERE id=%s', (claim,))
                rejected(con, "INSERT INTO claims(individual_id,author_user_id,claim_type,created_at,updated_at) VALUES(%s,2,'ownership','now','now')", (individual,))
                rejected(con, 'UPDATE individuals SET current_owner_user_id=2 WHERE id=%s', (individual,))
                rejected(con, 'DELETE FROM individuals WHERE id=%s', (individual,))
                # A non-ownership post remains writable while a dispute is open.
                con.execute("INSERT INTO claims(individual_id,author_user_id,claim_type,created_at,updated_at) VALUES(%s,2,'event','now','now')", (individual,))
            with connect(app,'chronicle') as con:
                dispute=con.execute('SELECT id FROM ownership_disputes WHERE individual_id=%s',(individual,)).fetchone()['id']
                con.execute("INSERT INTO ownership_dispute_evidence(dispute_id,claim_id,author_id,explanation,summary,content,created_at) VALUES(%s,%s,1,'Private explanation','',%s,'now')",(dispute,claim,bytes(range(256))))
            from ygc.cloud_db_snapshot import snapshot,verify_snapshot
            from ygc.cloud_backup_job import save,verify_latest
            from test_cloud_avatar import Storage
            from ygc.cloud_backup_routes import catalog
            from ygc.db.postgres_operations import PostgresOperations
            import hashlib
            storage=Storage()
            for target in TARGETS:
                data,metadata=snapshot(app,target)
                result=verify_snapshot(data,target,metadata['sha256'])
                assert result['tables']==status(app,target)['tables']
                assert save(app,storage,target,'fixture-execution')['read_back_verified']
                assert verify_latest(app,storage,target)['verified']
            assert len(storage.objects)==4
            # Metadata records are scoped; callers never receive storage references.
            with connect(app,'accounts') as con:
                con.execute("UPDATE account_records SET role='admin' WHERE app_user_id='test-uuid'")
            listing=catalog(PostgresOperations(app),'test-uuid','accounts')
            assert len(listing['items'])==1 and listing['items'][0]['target']=='accounts'
            assert 'object' not in listing['items'][0]
            with connect(owner,'operations') as con:
                con.execute(sql.SQL('REVOKE INSERT ON events FROM {}').format(sql.Identifier(runtime)))
            try:save(app,storage,'chronicle','failed-audit')
            except psycopg.errors.InsufficientPrivilege:pass
            else:raise AssertionError('Backup must fail when audit is denied.')
            assert len(storage.objects)==4 and len(storage.deleted)==1
            with connect(owner,'operations') as con:
                con.execute(sql.SQL('GRANT INSERT ON events TO {}').format(sql.Identifier(runtime)))
            print('PostgreSQL snapshots: all four targets, known schema/all tables/sequences, gzip integrity, independent save/read-back/catalog, audit rollback compensation passed.')
            with connect(owner, 'operations') as con:
                con.execute("ALTER TABLE settings ADD COLUMN unexpected TEXT")
            try:
                bootstrap(owner, 'operations', runtime)
            except ValueError:
                pass
            else:
                raise AssertionError('Schema drift must be rejected.')
            with connect(owner, 'authentication') as con:
                con.execute('DROP TABLE ygc_schema_version')
            try:
                bootstrap(owner, 'authentication', runtime)
            except ValueError:
                pass
            else:
                raise AssertionError('Unversioned existing schema must be rejected.')
            print('PostgreSQL: all four schemas, repeat bootstrap, runtime grants, identity/FK/JSON/dispute guards and drift checks passed.')
        finally:
            for name in reversed(created):
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--postgres-bin', type=Path)
    group.add_argument('--port', type=int)
    args = parser.parse_args()
    with server(args.postgres_bin, args.port) as port:
        initialization_checks(port)
        run(port)
        from postgres_account_checks import run as account_checks
        account_checks(port)

        from postgres_operations_checks import run as operations_checks
        operations_checks(port)
