"""Chronicle 003 migration and historical archive acceptance on disposable PG.

Importing this module never opens a connection or starts a server. The authorized
aggregate runner supplies loopback PostgreSQL 18; all objects are in-memory fake
storage and every fixture is synthetic. Production migration is never invoked.
"""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import uuid

import psycopg
from psycopg import errors, sql

from dispute_storage_fixtures import legacy_archive_fixture
from postgres_dispute_checks import PrivateStorage, PDF, STAMP, insert_original
from postgres_ownership_workflow_checks import rejected
from ygc.cloud_db_restore import load, replace_content
from ygc.cloud_db_snapshot import snapshot, verify_snapshot
from ygc.db import postgres
from ygc.db.postgres import PostgresSettings, bootstrap, connect, migrate, schema_versions, status
from ygc.db.postgres_queries import ObservationConnection


class RecordedConnection:
    def __init__(self, connection):
        self.connection, self.statements = connection, []

    def execute(self, query, *args, **kwargs):
        self.statements.append(query.as_string(self.connection) if hasattr(query, 'as_string') else query)
        return self.connection.execute(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.connection, name)


def constraints(con, legacy_evidence, evidence):
    """Exercise real trigger/CHECK/PK/UNIQUE enforcement using savepoints."""
    def denied(query, params, error=psycopg.Error):
        def operation():
            with con.transaction():
                con.execute(query, params)
        rejected(error, operation)

    denied('UPDATE ownership_dispute_originals SET byte_size=byte_size+1 WHERE evidence_id=%s', (evidence,))
    denied('UPDATE ownership_dispute_evidence SET content=%s WHERE id=%s', (PDF, evidence))
    denied("UPDATE ownership_dispute_evidence SET content_type='image/jpeg' WHERE id=%s", (evidence,))
    for field in ('dispute_id', 'claim_id', 'author_id'):
        denied(sql.SQL('UPDATE ownership_dispute_evidence SET {}={}+1 WHERE id=%s').format(
            sql.Identifier(field), sql.Identifier(field)), (evidence,), errors.RaiseException)
    denied('DELETE FROM ownership_dispute_evidence WHERE id=%s', (evidence,))
    row = dict(con.execute('SELECT * FROM ownership_dispute_originals WHERE evidence_id=%s', (evidence,)).fetchone())
    columns = list(row)
    statement = sql.SQL('INSERT INTO ownership_dispute_originals ({}) VALUES ({})').format(
        sql.SQL(',').join(map(sql.Identifier, columns)), sql.SQL(',').join(sql.Placeholder() for _ in columns))
    # The legacy row cannot gain a second competing original representation.
    denied(statement, tuple((row | {'evidence_id': legacy_evidence})[key] for key in columns))
    # Use a separate compatible, empty evidence row so an invalid constraint
    # cannot be hidden behind the existing row's primary-key conflict.
    target = con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,claim_id,author_id,
        explanation,summary,filename,content_type,created_at) SELECT dispute_id,claim_id,
        author_id,'Constraint fixture','Constraint fixture',filename,content_type,created_at
        FROM ownership_dispute_evidence WHERE id=%s RETURNING id''', (evidence,)).fetchone()['id']
    base = row | {'evidence_id': target, 'object_name': 'media/' + 'f' * 32}
    for invalid in ({'object_scope': 'accounts'}, {'object_name': 'https://invalid.example/proof'},
                    {'object_generation': 0}, {'byte_size': 0}, {'byte_size': 12582913},
                    {'content_type': 'text/html'}, {'content_type': 'image/jpeg'},
                    {'sha256': 'A' * 64}, {'sha256': '0' * 63}, {'created_at': ''}):
        denied(statement, tuple((base | invalid)[key] for key in columns))
    denied(statement, tuple((row | {'evidence_id': target})[key] for key in columns))
    assert con.execute('SELECT COUNT(*) AS n FROM ownership_dispute_originals WHERE evidence_id=%s', (evidence,)).fetchone()['n'] == 1
    assert con.execute('SELECT content FROM ownership_dispute_evidence WHERE id=%s', (legacy_evidence,)).fetchone()['content'] == PDF


def run(port):
    prefix = 'ygctest_dispute_storage_' + uuid.uuid4().hex[:10] + '_'
    role = prefix + 'app'
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port, prefix)
    runtime = replace(owner, user=role)
    name, created = owner.database('chronicle'), False
    storage = PrivateStorage()
    versions = schema_versions('chronicle')
    assert [row[0] for row in versions] == [1, 2, 3]
    assert 'ownership_dispute_originals' not in versions[1][2]['tables']
    assert versions[2][2]['tables']['ownership_dispute_originals'] == [
        'evidence_id', 'object_scope', 'object_name', 'object_generation', 'byte_size',
        'content_type', 'sha256', 'created_at']
    with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='postgres',
                         password='ygc-tests-only', autocommit=True) as system:
        try:
            system.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(role), sql.Literal('ygc-tests-only')))
            system.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created = True
            assert bootstrap(owner, 'chronicle', role)
            with connect(runtime, 'chronicle') as con:
                user, guitar, claim, case, evidence = legacy_archive_fixture(ObservationConnection(con), STAMP, PDF)
                current = [dict(user) | {'projection_version': 1}]
                sequences = {row['sequencename'] for row in con.execute(
                    "SELECT sequencename FROM pg_sequences WHERE schemaname='public'")}
            archives = []
            for version in (1, 2):
                if version == 2:
                    with patch.object(postgres, 'schema_versions', return_value=versions[:2]):
                        assert migrate(owner, 'chronicle', role) == [2]
                data, metadata = snapshot(runtime, 'chronicle')
                assert verify_snapshot(data, 'chronicle', metadata['sha256'])['schema_version'] == version
                header, rows, saved_sequences = load(data, 'chronicle', metadata['sha256'])
                assert header['schema_checksum'] == versions[version - 1][1]
                assert 'ownership_dispute_originals' not in rows
                assert rows['ownership_dispute_evidence'][0]['content'] == PDF
                archives.append((header, rows, saved_sequences))

            # DDL executes before this missing-role GRANT fails. Both DDL and
            # version/checksum must roll back; retry may then apply exactly 003.
            rejected(errors.UndefinedObject, lambda: migrate(owner, 'chronicle', role + '_missing'))
            assert status(runtime, 'chronicle')['version'] == 2
            with connect(runtime, 'chronicle') as con:
                assert con.execute("SELECT to_regclass('ownership_dispute_originals') AS name").fetchone()['name'] is None
                assert con.execute('SELECT checksum FROM ygc_schema_version WHERE id=1').fetchone()['checksum'] == versions[1][1]
                assert con.execute('SELECT content FROM ownership_dispute_evidence WHERE id=%s', (evidence,)).fetchone()['content'] == PDF
            assert migrate(owner, 'chronicle', role) == [3]
            assert migrate(owner, 'chronicle', role) == []
            assert not bootstrap(owner, 'chronicle', role)
            assert status(runtime, 'chronicle')['version'] == 3
            rejected(ValueError, lambda: migrate(runtime, 'chronicle', role))
            with connect(runtime, 'chronicle') as con:
                assert not con.execute('SELECT 1 FROM ownership_dispute_originals').fetchone()
                assert sequences == {row['sequencename'] for row in con.execute(
                    "SELECT sequencename FROM pg_sequences WHERE schemaname='public'")}
                assert not con.execute("SELECT has_schema_privilege(current_user,'public','CREATE') AS allowed").fetchone()['allowed']
                privileges = con.execute('''SELECT privilege_type FROM information_schema.role_table_grants
                    WHERE table_schema='public' AND table_name='ownership_dispute_originals'
                    AND grantee=current_user''').fetchall()
                assert {row['privilege_type'] for row in privileges} == {'SELECT', 'INSERT', 'UPDATE', 'DELETE'}

            for header, rows, saved_sequences in archives:
                original_header, original_rows = deepcopy(header), deepcopy(rows)
                with connect(runtime, 'chronicle') as con:
                    new_evidence = con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,
                        claim_id,author_id,explanation,summary,filename,content_type,created_at)
                        VALUES(%s,%s,%s,'Newer private proof','Newer private summary','document.pdf',
                        'application/pdf',%s) RETURNING id''',
                        (case, claim, user['id'], STAMP)).fetchone()['id']
                    reference = storage.put('content', PDF, content_type='application/pdf')
                    insert_original(con, new_evidence, reference, PDF)
                    constraints(con, evidence, new_evidence)
                with connect(runtime, 'chronicle') as con:
                    replace_content(con, header, rows, saved_sequences, current)
                # Restoration never forges a checksum or modifies the verified
                # historical input. Old bytes remain bytes; refs start empty.
                assert header == original_header and rows == original_rows
                with connect(runtime, 'chronicle') as con:
                    assert not con.execute('SELECT 1 FROM ownership_dispute_originals').fetchone()
                    assert con.execute('''SELECT manufacturer,model,serial_number,current_owner_user_id
                        FROM individuals WHERE id=%s''', (guitar,)).fetchone() == {
                            'manufacturer': 'Synthetic', 'model': 'Archive',
                            'serial_number': 'LEGACY-PROOF', 'current_owner_user_id': None}
                    assert not con.execute('SELECT 1 FROM user_guitars WHERE individual_id=%s', (guitar,)).fetchone()
                    assert con.execute('SELECT content FROM ownership_dispute_evidence WHERE id=%s', (evidence,)).fetchone()['content'] == PDF
                    assert not con.execute('SELECT 1 FROM ownership_dispute_evidence WHERE id=%s', (new_evidence,)).fetchone()
                    assert con.execute('SELECT version,checksum FROM ygc_schema_version WHERE id=1').fetchone() == {
                        'version': 3, 'checksum': versions[2][1]}
                assert reference in storage.objects and not storage.deleted

            # Invalid future versions, historical checksum drift and incompatible
            # columns all fail before the first data DELETE, even in real PG.
            header, rows, saved_sequences = archives[-1]
            for invalid in (header | {'schema_version': 4}, header | {'schema_checksum': '0' * 64},
                            header | {'tables': {**header['tables'], 'invented': ['id']}}):
                with connect(runtime, 'chronicle') as con:
                    recorded = RecordedConnection(con)
                    rejected(ValueError, lambda: replace_content(recorded, invalid, rows, saved_sequences, current))
                    assert not any('DELETE FROM' in str(query).upper() for query in recorded.statements)
                    assert con.execute('SELECT content FROM ownership_dispute_evidence WHERE id=%s', (evidence,)).fetchone()['content'] == PDF
            print('PostgreSQL dispute storage: atomic 002-to-003 DDL rollback/retry, unchanged historical '
                  'checksums and sequences, narrow runtime grants, v1/v2 legacy BYTEA restores into '
                  'empty reference table, retained objects and pre-delete future/drift rejection passed.')
        finally:
            if created:
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
