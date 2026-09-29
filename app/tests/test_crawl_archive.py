import hashlib
import json
import sqlite3

import pytest
from typer.testing import CliRunner

from ygc import config
from ygc.cli import app
from ygc.db.crawl_archive import archive_unregistered_crawl
from ygc.db.repository import Repository
from ygc.db.source_records import MARKETPLACE_SOURCES_SQL, known_listing_ids
from ygc.crawl_candidates import stage_candidate
from ygc.incremental_crawl import _recheck


def legacy_row(repo, listing_id='unregistered', site='reverb'):
    row = {
        'source_site': site, 'source_listing_id': listing_id,
        'source_url': 'https://example.test/listing', 'manufacturer': 'Fender',
        'model': 'Stratocaster', 'finish': 'Sunburst', 'year': '1965',
        'serial_number': None, 'owner_name': 'Shop', 'owner_type': 'shop',
        'owner_profile_url': 'https://example.test/shop', 'seller': 'Seller',
        'location_country': 'Japan', 'location_region': 'Tokyo',
        'location_source': 'listing', 'image_url': 'https://example.test/photo.jpg',
        'title': 'Vintage guitar', 'raw_text': '本文\nSerial uncertain: 12?34',
        'serial_confidence': 0.25, 'extraction_version': 'legacy-v1',
        'observed_at': '2026-09-01T00:00:00Z', 'listing_date': '2026-08-30',
        'created_at': '2026-09-01T00:00:01Z', 'event_type': 'listing',
    }
    with repo.connect() as con:
        cursor = con.execute(
            f'INSERT INTO observations ({",".join(row)}) VALUES ({",".join("?" for _ in row)})',
            list(row.values()),
        )
        return cursor.lastrowid


def test_full_rows_preserved_idempotently_without_other_database_changes(tmp_path):
    repo = Repository(tmp_path / 'archive.db')
    repo.init_db()
    legacy_row(repo)
    legacy_row(repo, None)  # Missing external ID is still worth preserving.
    legacy_row(repo, 'manual', 'user')
    with repo.connect() as con:
        # Future/unknown extraction columns must not silently disappear.
        con.execute('ALTER TABLE observations ADD COLUMN extra_extraction TEXT')
        con.execute("UPDATE observations SET extra_extraction='additional evidence'")
        before = list(con.iterdump())
        originals = {r['id']: dict(r) for r in con.execute('SELECT * FROM observations')}
    assert archive_unregistered_crawl(repo.db_path) == {
        'eligible': 2, 'created': 2, 'already_archived': 0, 'archive_total': 2}
    with repo.connect() as con:
        for archived in con.execute('SELECT * FROM legacy_crawl_archive'):
            assert json.loads(archived['payload_json']) == originals[archived['legacy_observation_id']]
            assert hashlib.sha256(archived['payload_json'].encode()).hexdigest() == archived['payload_sha256']
        after = [line for line in con.iterdump()
                 if not line.startswith('INSERT INTO "legacy_crawl_archive"')]
        assert after == before
        sources = con.execute(f'SELECT COUNT(*) FROM ({MARKETPLACE_SOURCES_SQL})').fetchone()[0]
        assert sources == 1  # Original + archive must not double-count a source.
    assert archive_unregistered_crawl(repo.db_path)['created'] == 0


@pytest.mark.parametrize('corruption', ['source', 'archive'])
def test_mismatch_aborts_entire_copy_and_never_overwrites(tmp_path, corruption):
    repo = Repository(tmp_path / 'conflict.db')
    repo.init_db()
    first = legacy_row(repo, 'first')
    second = legacy_row(repo, 'second')
    archive_unregistered_crawl(repo.db_path)
    with repo.connect() as con:
        # A new copy would be inserted before the conflict is encountered.
        con.execute('DELETE FROM legacy_crawl_archive WHERE legacy_observation_id=?', (first,))
        if corruption == 'source':
            con.execute("UPDATE observations SET raw_text='changed' WHERE id=?", (second,))
        else:
            con.execute("UPDATE legacy_crawl_archive SET payload_sha256='broken' WHERE legacy_observation_id=?", (second,))
        before = list(con.iterdump())
    with pytest.raises(ValueError, match='mismatch'):
        archive_unregistered_crawl(repo.db_path)
    with repo.connect() as con:
        assert list(con.iterdump()) == before


def test_archive_keeps_deduplication_after_legacy_removal_and_backup_restore(tmp_path, monkeypatch):
    repo = Repository(tmp_path / 'source.db')
    repo.init_db()
    legacy_row(repo)
    archive_unregistered_crawl(repo.db_path)
    with repo.connect() as con:
        con.execute('DELETE FROM observations')  # Disposable migration rehearsal only.
    claim = {'manufacturer': 'Fender', 'model': 'Stratocaster', 'serial_number': '12345'}
    provenance = {'source_site': 'reverb', 'source_listing_id': 'unregistered'}
    with repo.connect() as con:
        assert known_listing_ids(con, 'reverb', ['unregistered']) == {'unregistered'}
        assert known_listing_ids(con, 'other', ['unregistered']) == set()
        with sqlite3.connect(tmp_path / 'restored.db') as restored:
            con.backup(restored)
    restored = Repository(tmp_path / 'restored.db')
    restored.init_db()
    assert not stage_candidate(restored, claim, provenance)
    assert not restored.persist_reverb_listing_claim(claim, provenance)['created']
    assert archive_unregistered_crawl(restored.db_path)['archive_total'] == 1
    monkeypatch.setattr('ygc.incremental_crawl.MIN_REQUEST_GAP', 0)
    class Collector:
        def public_listing_status(self, listing_id, api_url=None):
            assert listing_id == 'unregistered'
            return 'missing'
    first, _ = _recheck(restored, Collector(), 0)
    assert first['missing_first_check'] == 1
    with restored.connect() as con:
        con.execute("UPDATE crawl_listing_checks SET checked_at='2000-01-01T00:00:00+00:00', "
                    "missing_since='2000-01-01T00:00:00+00:00'")
    second, _ = _recheck(restored, Collector(), 0)
    assert second['confirmed_missing'] == 1
    assert second['unavailable_claims'] == 0  # No invented Claim for unregistered history.
    audit = restored.audit_observation_migration()
    assert audit['unregistered_legacy_crawl_rows'] == 0
    assert audit['archived_unregistered_crawl_rows'] == 1
    with restored.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM individuals').fetchone()[0] == 0
        assert con.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == 0
        assert json.loads(con.execute('SELECT payload_json FROM legacy_crawl_archive').fetchone()[0])['raw_text'].startswith('本文')


def test_archive_cli_does_not_create_missing_database(tmp_path, monkeypatch):
    path = tmp_path / 'missing.db'
    monkeypatch.setattr(config, 'DB_PATH', path)
    result = CliRunner().invoke(app, ['archive-unregistered-crawl'])
    assert result.exit_code != 0
    assert not path.exists()


def test_registered_claims_and_evidence_are_excluded(tmp_path, legacy_marketplace_row):
    repo = Repository(tmp_path / 'linked.db')
    repo.init_db()
    claim = {'manufacturer': 'Fender', 'model': 'Stratocaster', 'serial_number': '12345'}
    provenance = {'source_site': 'reverb', 'source_listing_id': 'registered',
                  'source_url': 'https://example.test/registered'}
    result = repo.persist_reverb_listing_claim(claim, provenance)
    old_id = legacy_marketplace_row(repo, result, claim, provenance)
    # Even inconsistent legacy rows must not archive a linked Claim as unregistered.
    with repo.connect() as con:
        con.execute('UPDATE observations SET individual_id=NULL WHERE id=?', (old_id,))
    assert archive_unregistered_crawl(repo.db_path)['eligible'] == 0
