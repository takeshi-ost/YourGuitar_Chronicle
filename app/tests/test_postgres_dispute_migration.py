"""Packaged migration and read-only schema gates, without a database server."""
from contextlib import contextmanager
import copy
import shutil
from unittest.mock import Mock

import pytest

from dispute_storage_fixtures import legacy_archive_fixture
from ygc.db import postgres
from ygc.db.repository import Repository
from ygc import cloud_disputes
from ygc.cloud_dispute_storage import ORIGINAL_COLUMNS


def test_legacy_archive_fixture_supports_projection_rebuild_without_changing_ownership(tmp_path):
    repo = Repository(tmp_path / 'archive-fixture.db')
    repo.init_db()
    content = b'%PDF-1.4 synthetic archive proof\n%%EOF'
    with repo.connect() as con:
        con.execute('ALTER TABLE users ADD COLUMN app_user_id TEXT')
        user, guitar, claim, case, evidence = legacy_archive_fixture(con, '2026-06-01T12:00:00+00:00', content)
        # Exercise the same Observation rebuild required by Account projection
        # during a Chronicle restore, without a PostgreSQL server.
        for name in ('Synthetic archive member', 'Renamed archive member'):
            con.execute('UPDATE users SET display_name=? WHERE id=?', (name, user['id']))
            repo._rebuild_individual_snapshot_in_connection(con, guitar)
            assert dict(con.execute('''SELECT manufacturer,model,serial_number,current_owner_user_id
                FROM individuals WHERE id=?''', (guitar,)).fetchone()) == {
                    'manufacturer': 'Synthetic', 'model': 'Archive',
                    'serial_number': 'LEGACY-PROOF', 'current_owner_user_id': None}
            assert not con.execute('SELECT 1 FROM user_guitars WHERE individual_id=?', (guitar,)).fetchone()
            assert dict(con.execute('''SELECT dispute_id,claim_id,author_id,content
                FROM ownership_dispute_evidence WHERE id=?''', (evidence,)).fetchone()) == {
                    'dispute_id': case, 'claim_id': claim, 'author_id': user['id'], 'content': content}
        assert con.execute('SELECT claim_type FROM claims WHERE id=?', (claim,)).fetchone()['claim_type'] == 'event'
        assert not con.execute('SELECT 1 FROM media_assets').fetchone()
        # This must remain a fixture repair, never permission to restore an
        # Individual whose active Claims cannot establish its identity.
        con.execute("UPDATE claims SET status='inactive' WHERE individual_id=? AND claim_type='listing'", (guitar,))
        with pytest.raises(ValueError, match='Active Claims do not define a complete Individual identity'):
            repo._rebuild_individual_snapshot_in_connection(con, guitar)


def test_additive_originals_version_keeps_historical_schemas():
    versions = postgres.schema_versions('chronicle')
    assert [revision[0] for revision in versions] == [1, 2, 3]
    for _, _, expected, _ in versions[:2]:
        assert 'ownership_dispute_originals' not in expected['tables']
    base = versions[1][2]['tables']
    current = versions[2][2]['tables']
    assert {name: current[name] for name in base} == base
    assert current['ownership_dispute_originals'] == list(ORIGINAL_COLUMNS)
    migration = versions[2][3]
    assert 'REFERENCES ownership_dispute_evidence(id)' in migration
    assert "object_scope='content'" in migration and 'byte_size<=12582912' in migration
    assert 'FOR UPDATE' in migration and 'e.content IS NULL' in migration
    assert 'e.content_type=NEW.content_type' in migration
    assert "IF TG_OP='UPDATE'" in migration
    assert 'BEFORE UPDATE OF id,dispute_id,claim_id,author_id,content,content_type' in migration
    for column in ('dispute_id', 'claim_id', 'author_id'):
        assert 'NEW.' + column + ' IS DISTINCT FROM OLD.' + column in migration
    assert 'DELETE FROM' not in migration and 'UPDATE ownership_dispute_evidence' not in migration
    assert 'BEFORE DELETE' not in migration
    for version, checksum, expected, _ in versions:
        assert postgres.recorded_schema('chronicle', {'version': version, 'checksum': checksum}) == expected


def test_modified_migration_rejected_before_any_database_work(tmp_path, monkeypatch):
    artifacts = tmp_path / 'postgres'
    shutil.copytree(postgres.ARTIFACTS, artifacts)
    with (artifacts / 'chronicle_003.sql').open('a') as out:
        out.write('\n-- unapproved mutation\n')
    monkeypatch.setattr(postgres, 'ARTIFACTS', artifacts)
    connect = Mock(side_effect=AssertionError('Must reject before database access'))
    monkeypatch.setattr(postgres, 'connect', connect)
    with pytest.raises(ValueError, match='checksum'):
        postgres.migrate(object(), 'chronicle')
    connect.assert_not_called()


@pytest.mark.parametrize('validation_fails', [False, True])
def test_migration_uses_one_atomic_transaction_existing_crud_grants(monkeypatch, validation_fails):
    versions = postgres.schema_versions('chronicle')
    previous, latest = versions[-2], versions[-1]
    state = {'version': previous[0], 'checksum': previous[1]}
    queries, outcomes = [], []
    class Connection:
        def execute(self, query, args=None, **kwargs):
            value = str(query)
            queries.append((value, args))
            if value == 'SELECT current_user AS name':
                return Mock(fetchone=Mock(return_value={'name': 'schema_owner'}))
            if 'SELECT version,checksum' in value:
                return Mock(fetchone=Mock(return_value=dict(state)))
            if value.startswith('UPDATE ygc_schema_version'):
                state.update(version=args[0], checksum=args[1])
            return Mock()
    @contextmanager
    def transaction(settings, target):
        assert target == 'chronicle'
        before = copy.deepcopy(state)
        try:
            yield Connection()
        except Exception:
            state.clear()
            state.update(before)
            outcomes.append('rollback')
            raise
        else:
            outcomes.append('commit')
    def validate(connection, expected):
        if validation_fails and 'ownership_dispute_originals' in expected['tables']:
            raise ValueError('Synthetic final schema failure')
    monkeypatch.setattr(postgres, 'connect', transaction)
    monkeypatch.setattr(postgres, 'validate_schema', validate)
    if validation_fails:
        with pytest.raises(ValueError, match='Synthetic'):
            postgres.migrate(object(), 'chronicle')
        assert state == {'version': previous[0], 'checksum': previous[1]}
        assert outcomes == ['rollback']
    else:
        assert postgres.migrate(object(), 'chronicle') == [3]
        assert state == {'version': latest[0], 'checksum': latest[1]}
        assert outcomes == ['commit']
        assert postgres.migrate(object(), 'chronicle') == []
    assert sum(query == latest[3] for query, _ in queries) == 1
    grants = [query for query, _ in queries if 'GRANT' in query]
    assert grants and all('SELECT, INSERT, UPDATE, DELETE ON TABLE' in query
                          or 'USAGE, SELECT ON ALL SEQUENCES' in query for query in grants)


@pytest.mark.parametrize('version', [1, 2, 3])
def test_runtime_schema_check_requires_known_v3_without_migration(monkeypatch, version):
    status = Mock(return_value={'target': 'chronicle', 'version': version, 'tables': 1})
    monkeypatch.setattr(cloud_disputes, 'database_status', status)
    service = cloud_disputes.CloudDisputes('settings', None)
    if version < 3:
        with pytest.raises(RuntimeError, match='migration'):
            service.check_schema()
    else:
        assert service.check_schema()['version'] == 3
    status.assert_called_once_with('settings', 'chronicle')


def test_runtime_schema_check_propagates_unknown_or_damaged_schema(monkeypatch):
    monkeypatch.setattr(cloud_disputes, 'database_status', Mock(side_effect=ValueError('Unknown schema')))
    service = cloud_disputes.CloudDisputes(None, None)
    with pytest.raises(ValueError, match='Unknown'):
        service.check_schema()
    with pytest.raises(ValueError, match='Unknown'):
        with service.transaction('actor', case=1):
            pass


@pytest.mark.parametrize('known_versions', [1, 2])
def test_old_reader_rejects_v3_read_only_without_relabeling_or_dropping_references(monkeypatch, known_versions):
    versions = postgres.schema_versions('chronicle')
    latest = versions[-1]
    stored = {'version': latest[0], 'checksum': latest[1],
              'originals': [{'evidence_id': 123, 'object_generation': 9007199254741009}]}
    before = copy.deepcopy(stored)
    queries = []

    class ReadOnlyConnection:
        def execute(self, query, *args, **kwargs):
            queries.append(query)
            assert query == 'SELECT version,checksum FROM ygc_schema_version WHERE id=1'
            return Mock(fetchone=Mock(return_value={key: stored[key] for key in ('version', 'checksum')}))

    @contextmanager
    def connection(settings, target):
        assert target == 'chronicle'
        yield ReadOnlyConnection()

    # Model the exact immutable revisions packaged by an older reader. It may
    # refuse the current database, but may never relabel003 as002 or erase refs.
    monkeypatch.setattr(postgres, 'schema_versions', lambda target: versions[:known_versions])
    monkeypatch.setattr(postgres, 'connect', connection)
    with pytest.raises(ValueError, match='Unknown schema version/checksum'):
        postgres.status(object(), 'chronicle')
    assert queries == ['SELECT version,checksum FROM ygc_schema_version WHERE id=1']
    assert stored == before
