"""Disposable PostgreSQL acceptance for HTTP connection reuse and isolation."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import uuid
import psycopg
from psycopg import sql
from ygc.db.postgres import PostgresSettings, connect
from ygc.db.postgres_pool import RuntimeConnectionPools


def run(port):
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port,
                             'ygctest_pool_' + uuid.uuid4().hex[:10] + '_')
    names = [owner.database(target) for target in ('accounts', 'operations')]
    with psycopg.connect(host=owner.host, port=port, user=owner.user, password=owner.password,
                         dbname='postgres', autocommit=True) as system:
        for name in names:
            system.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        pools = RuntimeConnectionPools(owner, max_size=1, timeout=2)
        settings = replace(owner, pool=pools)
        try:
            with connect(owner, 'accounts') as con:
                con.execute('CREATE TABLE pool_probe(value INTEGER)')
            with connect(settings, 'accounts') as con:
                pid = con.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid']
                con.execute('INSERT INTO pool_probe VALUES(1)')
                con.execute('CREATE TEMP TABLE pool_temp(value INTEGER)')
                con.execute("SET statement_timeout='1s'")
                con.execute('SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY')
                # The nested reader must not borrow its own held lease or see
                # uncommitted writes, even when the one-slot pool is saturated.
                with connect(settings, 'accounts') as inner:
                    assert inner.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'] != pid
                    assert inner.execute('SELECT count(*) AS n FROM pool_probe').fetchone()['n'] == 0
            with connect(settings, 'accounts') as con:
                assert con.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'] == pid
                assert con.execute('SELECT count(*) AS n FROM pool_probe').fetchone()['n'] == 1
                assert con.execute("SELECT to_regclass('pg_temp.pool_temp') AS temp").fetchone()['temp'] is None
                assert con.execute('SHOW statement_timeout').fetchone()['statement_timeout'] == '1min'
                assert con.execute('SHOW default_transaction_read_only').fetchone()['default_transaction_read_only'] == 'off'
                assert con.prepare_threshold is None
            try:
                with connect(settings, 'accounts') as con:
                    con.execute('INSERT INTO pool_probe VALUES(2)')
                    con.execute('SELECT 1/0')
            except psycopg.errors.DivisionByZero:
                pass
            else:
                raise AssertionError('Expected failed transaction')
            def write(value):
                with connect(settings, 'accounts') as con:
                    con.execute('INSERT INTO pool_probe VALUES(%s)', (value,))
            with ThreadPoolExecutor(max_workers=4) as workers:
                list(workers.map(write, range(10, 14)))
            with connect(settings, 'accounts') as con:
                assert con.execute('SELECT count(*) AS n FROM pool_probe').fetchone()['n'] == 5
            # Another thread can saturate a different store. Holding Accounts
            # must not wait for Operations and create a cross-store wait cycle.
            held, release = Event(), Event()
            other_pid = []
            def hold_other_store():
                with connect(settings, 'operations') as other:
                    other_pid.append(other.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'])
                    held.set()
                    assert release.wait(3)
            with ThreadPoolExecutor(max_workers=1) as worker:
                future = worker.submit(hold_other_store)
                assert held.wait(3)
                try:
                    with connect(settings, 'accounts') as con:
                        with connect(settings, 'operations') as nested:
                            assert nested.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'] != other_pid[0]
                finally:
                    release.set()
                future.result()
            # Broken leases fail the current operation; never replay a write.
            with connect(owner, 'accounts') as con:
                con.execute('SELECT pg_terminate_backend(%s)', (pid,))
            try:
                with connect(settings, 'accounts') as con:
                    con.execute('SELECT 1')
            except psycopg.OperationalError:
                pass
            with connect(settings, 'accounts') as con:
                assert con.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'] != pid
                assert con.execute('SELECT count(*) AS n FROM pool_probe').fetchone()['n'] == 5
            pools.close()
            try:
                with connect(settings, 'accounts'):
                    pass
            except RuntimeError:
                pass
            else:
                raise AssertionError('Closed pool cannot create a new lease')
            print('PostgreSQL pool: PID reuse, commit/rollback, reset/temp/read-only isolation, nested saturated lease, concurrent writes, broken recovery and shutdown passed.', flush=True)
        finally:
            pools.close()
            for name in reversed(names):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
