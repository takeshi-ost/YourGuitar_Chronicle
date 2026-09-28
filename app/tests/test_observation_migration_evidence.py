"""The first migration phase copies source evidence without changing Individuals."""
import sqlite3
from pathlib import Path

from ygc.db.repository import Repository


def _reverb_item(listing_id: str) -> tuple[dict, dict]:
    claim = {
        'manufacturer': 'Fender', 'model': 'Stratocaster', 'serial_number': '524436',
        'year': '1974', 'owner_name': 'Shop', 'owner_type': 'shop',
        'location_country': 'US', 'location_region': 'CA',
        'listing_date': '2026-09-20', 'source_url': f'https://example.test/{listing_id}',
        'source_site': 'reverb', 'source_listing_id': listing_id,
    }
    provenance = {
        'source_site': 'reverb', 'source_listing_id': listing_id,
        'source_url': f'https://example.test/{listing_id}',
        'observed_at': '2026-09-25T00:00:00+00:00',
        'listing_date': '2026-09-20', 'raw_text': 'Serial 524436',
    }
    return claim, provenance


def test_live_reverb_writes_claim_evidence_for_initial_and_relisting(tmp_path):
    repo = Repository(tmp_path / 'chronicle.db')
    repo.init_db()
    first = repo.persist_reverb_listing_claim(*_reverb_item('100'))
    second = repo.persist_reverb_listing_claim(*_reverb_item('200'))
    assert first['individual_id'] == second['individual_id']
    with repo.connect() as con:
        evidence = con.execute('SELECT * FROM claim_source_evidence ORDER BY id').fetchall()
        assert [row['claim_id'] for row in evidence] == [first['claim_id'], second['claim_id']]
        assert [row['source_listing_id'] for row in evidence] == ['100', '200']
        assert [row['date_basis'] for row in evidence] == ['listing_date', 'observed_at']
        assert con.execute('SELECT count(*) FROM observations').fetchone()[0] == 2
    assert repo.backfill_claim_source_evidence() == {'created': 0, 'existing': 2, 'conflicts': 0}


def test_old_snapshot_copy_backfills_without_affecting_unregistered_crawl_rows(tmp_path):
    source = Path(__file__).parent / 'data/ygc_test_snapshot.db'
    if not source.exists():
        return
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as old, sqlite3.connect(path) as target:
        old.backup(target)
    repo = Repository(path)
    repo.init_db()
    with repo.connect() as con:
        individual_states = [tuple(row) for row in con.execute(
            'SELECT id,manufacturer,model,serial_number,current_owner_name,location_country '
            'FROM individuals ORDER BY id')]
        before = {table: con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                  for table in ('observations', 'claims', 'individuals')}
        linked = con.execute("""SELECT count(*) FROM observations o
                                WHERE o.source_site <> 'user' AND o.source_listing_id IS NOT NULL
                                AND EXISTS (SELECT 1 FROM claims c WHERE c.observation_id=o.id
                                  AND (c.claim_type='listing' OR
                                    (c.claim_type='ownership' AND c.ownership_kind='acquire')))""").fetchone()[0]
        orphaned = con.execute('SELECT count(*) FROM observations WHERE individual_id IS NULL').fetchone()[0]
    first = repo.backfill_claim_source_evidence()
    assert first['created'] == linked
    assert first['conflicts'] == 0
    second = repo.backfill_claim_source_evidence()
    assert second['created'] == 0 and second['conflicts'] == 0
    with repo.connect() as con:
        assert con.execute('SELECT count(*) FROM claim_source_evidence').fetchone()[0] == linked
        assert con.execute('SELECT count(*) FROM observations WHERE individual_id IS NULL').fetchone()[0] == orphaned
        assert {table: con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                for table in before} == before
        assert [tuple(row) for row in con.execute(
            'SELECT id,manufacturer,model,serial_number,current_owner_name,location_country '
            'FROM individuals ORDER BY id')] == individual_states
