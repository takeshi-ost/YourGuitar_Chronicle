"""Real mode matrix, canonical role fencing, audit rollback and initial Admin."""
import json
import uuid
import psycopg
from psycopg import sql
from ygc.db.postgres import PostgresSettings, bootstrap, migrate, connect
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ModeConflict, MODES
from ygc.admin_bootstrap_job import grant_first_admin


def run(port):
    prefix = 'ygctest_' + uuid.uuid4().hex[:12] + '_'
    role = prefix + 'app'
    owner = PostgresSettings('127.0.0.1','postgres','ygc-tests-only',port,prefix)
    app = PostgresSettings('127.0.0.1',role,'ygc-tests-only',port,prefix)
    created = []
    def rejected(kind, operation):
        try: operation()
        except kind: return
        raise AssertionError('Expected ' + kind.__name__)
    with psycopg.connect(host='127.0.0.1',port=port,dbname='postgres',user='postgres',password='ygc-tests-only',autocommit=True) as admin:
        try:
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role),sql.Literal('ygc-tests-only')))
            for target in ('accounts','chronicle','operations'):
                name = owner.database(target)
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                created.append(name)
                bootstrap(owner,target,role)
                migrate(owner,target,role)
            accounts, operations = PostgresAccounts(app), PostgresOperations(app)
            a = accounts.ensure_identity(issuer='issuer',subject='admin',display_name='Admin')
            b = accounts.ensure_identity(issuer='issuer',subject='member',display_name='Member')
            aid, bid = a['app_user_id'], b['app_user_id']
            assert grant_first_admin(app,aid,'test-operator')
            assert not grant_first_admin(app,aid,'test-operator')
            rejected(PermissionError,lambda: grant_first_admin(app,bid,'test-operator'))
            with connect(app,'accounts') as con:
                assert con.execute("SELECT COUNT(*) AS n FROM account_metadata WHERE key LIKE 'admin_bootstrap:%'").fetchone()['n'] == 1
            assert operations.public_status()['mode'] == 'offline'
            version = 0
            for mode in MODES:
                state = operations.set_mode(aid,mode=mode,message='Test',version=version)
                version = state['version']
                assert operations.details(aid)['mode'] == mode
                for actor in (None,bid,aid):
                    for kind in ('public_read','user_read','user_write','admin_read','admin_write'):
                        expected = ((kind.startswith('admin_') and actor==aid) or
                            (not kind.startswith('admin_') and (not kind.startswith('user_') or actor is not None) and
                             (mode=='normal' or (mode=='read_only' and kind.endswith('_read')) or (mode=='admin_only' and actor==aid))))
                        def access():
                            with operations.access(kind,actor): pass
                        if expected: access()
                        else: rejected(PermissionError,access)
            rejected(ModeConflict,lambda: operations.set_mode(aid,mode='normal',message='',version=0))
            rejected(ValueError,lambda: operations.set_mode(aid,mode='invalid',message='',version=version))
            with connect(app,'operations') as con:
                assert con.execute('SELECT COUNT(*) AS n FROM events').fetchone()['n'] == 4
                audit = json.loads(con.execute('SELECT reason FROM events ORDER BY id LIMIT 1').fetchone()['reason'])
                assert audit['actor_app_user_id'] == aid
            # A failed audit must roll back the mode update too.
            with connect(owner,'operations') as con:
                con.execute(sql.SQL('REVOKE INSERT ON events FROM {}').format(sql.Identifier(role)))
            rejected(psycopg.errors.InsufficientPrivilege,lambda: operations.set_mode(aid,mode='normal',message='',version=version))
            assert operations.details(aid)['version'] == version
            with connect(owner,'operations') as con:
                con.execute(sql.SQL('GRANT INSERT ON events TO {}').format(sql.Identifier(role)))
            # Role changes cannot race an admitted administrative operation.
            with operations.access('admin_read',aid):
                def revoke():
                    with connect(app,'accounts') as con:
                        con.execute('SET statement_timeout=100')
                        con.execute("UPDATE account_records SET role='member' WHERE app_user_id=%s",(aid,))
                rejected(psycopg.errors.QueryCanceled,revoke)
            with connect(app,'accounts') as con:
                con.execute("UPDATE account_records SET role='member' WHERE app_user_id=%s",(aid,))
            rejected(PermissionError,lambda: operations.details(aid))
            with connect(app,'accounts') as con:
                con.execute("UPDATE account_records SET role='admin',disabled=1 WHERE app_user_id=%s",(aid,))
            rejected(PermissionError,lambda: operations.details(aid))
            print('PostgreSQL operations: all modes/actors, first Admin, repeat/refusal, version conflict, audit rollback and live role fencing passed.')
        finally:
            for name in reversed(created): admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
