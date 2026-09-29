"""Current reads survive removal of migrated legacy rows on a disposable DB."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ygc import config
from ygc.cli import app as cli_app
from ygc.crawl_candidates import stage_candidate
from ygc.crawl_detail_cache import reprocess_details, save_detail
from ygc.crawl_service import existing_listing_ids
from ygc.db.repository import Repository
from ygc.db.source_records import known_listing_ids
from ygc.incremental_crawl import _known_listing_ids, _recheck
from ygc.web import app


def source(listing_id):
    claim = {'manufacturer': 'Fender', 'model': 'Stratocaster',
             'serial_number': 'SOURCE-123', 'owner_name': 'Shop', 'owner_type': 'shop',
             'source_site': 'reverb', 'source_listing_id': listing_id,
             'source_url': f'https://example.test/{listing_id}'}
    provenance = {'source_site': 'reverb', 'source_listing_id': listing_id,
                  'source_url': claim['source_url'], 'observed_at': '2026-09-20T12:00:00Z',
                  'image_url': f'https://example.test/{listing_id}.jpg',
                  'raw_text': 'Serial SOURCE-123'}
    return claim, provenance


def remove_migrated_rows(repo):
    with repo.connect() as con:
        con.execute('UPDATE claims SET observation_id=NULL WHERE observation_id IN '
                    '(SELECT legacy_observation_id FROM claim_source_evidence)')
        con.execute('DELETE FROM observations WHERE id IN '
                    '(SELECT legacy_observation_id FROM claim_source_evidence)')


class Collector:
    def __init__(self):
        self.checked = []

    def listing_id(self, item):
        return item['id']

    def public_listing_status(self, listing_id, api_url=None):
        self.checked.append(listing_id)
        return 'missing'


def test_all_crawl_entries_skip_evidence_sources_and_preserve_unregistered_history(tmp_path, legacy_marketplace_row):
    repo = Repository(tmp_path / 'sources.db')
    repo.init_db()
    first = repo.persist_reverb_listing_claim(*source('first'))
    legacy_marketplace_row(repo, first, *source('first'))
    remove_migrated_rows(repo)
    with repo.connect() as con:
        con.execute("INSERT INTO observations(source_site,source_listing_id,source_url,"
                    "observed_at,created_at) VALUES ('reverb','unregistered','legacy','2020','2020')")
    ids = ['first', 'unregistered'] + [f'new-{i}' for i in range(600)]
    with repo.connect() as con:
        assert known_listing_ids(con, 'reverb', ids) == {'first', 'unregistered'}
        assert known_listing_ids(con, 'other-site', ids) == set()
        assert known_listing_ids(con, 'reverb', []) == set()
    assert existing_listing_ids(repo, ids) == {'first', 'unregistered'}
    assert _known_listing_ids(repo, Collector(), [{'id': i} for i in ids]) == {'first', 'unregistered'}
    assert not stage_candidate(repo, *source('first'))
    assert not stage_candidate(repo, *source('unregistered'))
    save_detail(repo, 'first', {'id': 'first'})
    save_detail(repo, 'unregistered', {'id': 'unregistered'})
    result = reprocess_details(repo, 'electric', 1950, 1980)
    assert result['skipped_existing'] == 2
    assert result['new_individuals'] == 0
    with repo.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM observations WHERE individual_id IS NULL').fetchone()[0] == 1
        # Moderation must not make a processed listing eligible for duplicate crawling.
        con.execute("UPDATE claims SET status='inactive'")
        assert known_listing_ids(con, 'reverb', ['first']) == {'first'}


def test_public_recheck_uses_evidence_once_and_creates_lost_without_legacy_rows(tmp_path, monkeypatch, legacy_marketplace_row):
    monkeypatch.setattr('ygc.incremental_crawl.MIN_REQUEST_GAP', 0)
    repo = Repository(tmp_path / 'recheck.db')
    repo.init_db()
    listing = repo.persist_reverb_listing_claim(*source('first'))
    legacy_marketplace_row(repo, listing, *source('first'))
    collector = Collector()
    first, _ = _recheck(repo, collector, 0)
    assert first['missing_first_check'] == 1
    assert collector.checked == ['first']  # Evidence plus legacy row is one source.
    remove_migrated_rows(repo)
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with repo.connect() as con:
        con.execute('UPDATE crawl_listing_checks SET checked_at=?,missing_since=?', (old, old))
    second, _ = _recheck(repo, collector, 0)
    assert collector.checked == ['first', 'first']
    assert second['unavailable_claims'] == 1
    assert repo.get_individual(listing['individual_id'])[0]['current_owner_name'] == 'Unknown'
    with repo.connect() as con:
        lost = con.execute("SELECT * FROM claims WHERE ownership_kind='lost'").fetchone()
        assert lost['target_claim_id'] == listing['claim_id']
        assert lost['observation_id'] is None
    assert repo.observation_diagnostic(listing['individual_id'])['differences'] == {}


def test_serial_listing_counts_and_pending_acquire_sources_survive_removal(tmp_path):
    repo = Repository(tmp_path / 'pending.db')
    repo.init_db()
    first = repo.persist_reverb_listing_claim(*source('first'))
    owner = repo.create_user('Owner')
    repo.create_ownership_claim(owner, first['individual_id'], ownership_kind='acquire',
                                occurred_at='2026-09-21')
    claim, provenance = source('second')
    provenance['observed_at'] = '2026-09-22T12:00:00Z'
    second = repo.persist_reverb_listing_claim(claim, provenance)
    before = repo.unverified_acquires()
    assert before['total'] == 1
    assert repo.stats()['serial_observations'] == 2
    remove_migrated_rows(repo)
    assert repo.unverified_acquires() == before
    assert repo.stats()['serial_observations'] == 2
    assert before['items'][0]['claim_id'] == second['claim_id']
    assert before['items'][0]['source_listing_id'] == 'second'


def test_migrated_image_and_discovery_use_evidence_without_legacy_history(tmp_path, monkeypatch, legacy_marketplace_row):
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'web.db')
    repo = Repository(config.DB_PATH)
    repo.init_db()
    first = repo.persist_reverb_listing_claim(*source('first'))
    legacy_marketplace_row(repo, first, *source('first'))
    with repo.connect() as con:
        # Reproduce an old database migrated through the source-payload format.
        con.execute('DELETE FROM claim_source_evidence')
        con.execute("DELETE FROM claim_listing_items WHERE field_name='image_url'")
    assert repo.backfill_claim_source_evidence()['created'] == 1
    with TestClient(app) as client:
        url = f"/api/individuals/{first['individual_id']}"
        detail = client.get(url).json()
        assert 'observations' not in detail
        assert 'observations' not in client.get(url + '?include_legacy_observations=true').json()
        assert detail['current_source']['image_url'] == source('first')[1]['image_url']
        before = client.get('/api/new-discoveries').json()
        assert len(before) == 1
        remove_migrated_rows(repo)
        for field in ('current_listing', 'current_source'):
            detail[field]['observation_id'] = None  # Removed compatibility link only.
        assert client.get(url).json() == detail
        assert client.get('/api/new-discoveries').json() == before
        # A banned source must not reappear through old discovery timestamps.
        with repo.connect() as con:
            con.execute("UPDATE users SET ban_status='ban' WHERE id IN (SELECT author_user_id FROM claims)")
        assert client.get('/api/new-discoveries').json() == []


def test_cli_show_displays_new_evidence_only_listing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'cli.db')
    repo = Repository(config.DB_PATH)
    repo.init_db()
    first = repo.persist_reverb_listing_claim(*source('first'))
    assert first['observation_id'] is None
    result = CliRunner().invoke(cli_app, ['show', str(first['individual_id'])])
    assert result.exit_code == 0, result.output
    assert f"#{first['claim_id']} listing" in result.output
    assert 'SOURCE-123' in result.output
    legacy = CliRunner().invoke(cli_app, ['show', str(first['individual_id']), '--legacy-observations'])
    assert legacy.exit_code != 0


def test_native_unregistered_records_keep_complete_inputs_dedup_and_restore(tmp_path, monkeypatch):
    repo = Repository(tmp_path / 'native.db')
    repo.init_db()
    claim, provenance = source('unregistered-native')
    claim['serial_number'] = None
    claim['additional_extraction'] = {'candidates': ['123?', '456?']}
    provenance['raw_detail'] = {'images': ['original.jpg'], 'description': 'Original text'}
    result = repo.persist_reverb_listing_claim(claim, provenance)
    assert result['created'] and result['crawl_record_id'] > 0
    assert result['observation_id'] is result['individual_id'] is result['claim_id'] is None
    with repo.connect() as con:
        row = con.execute('SELECT * FROM crawl_unregistered_records').fetchone()
        assert json.loads(row['payload_json']) == {'claim': claim, 'provenance': provenance}
        assert row['reason'] == 'missing_identity'
        assert con.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0
        with sqlite3.connect(tmp_path / 'restored.db') as backup:
            con.backup(backup)
    restored = Repository(tmp_path / 'restored.db')
    restored.init_db()
    assert not restored.persist_reverb_listing_claim(claim, provenance)['created']
    assert not stage_candidate(restored, claim, provenance)
    assert existing_listing_ids(restored, ['unregistered-native']) == {'unregistered-native'}
    save_detail(restored, 'unregistered-native', {'id': 'unregistered-native'})
    assert reprocess_details(restored, 'electric', 1950, 1980)['skipped_existing'] == 1
    monkeypatch.setattr('ygc.incremental_crawl.MIN_REQUEST_GAP', 0)
    collector = Collector()
    counts, _ = _recheck(restored, collector, 0)
    assert counts['missing_first_check'] == 1
    assert collector.checked == ['unregistered-native']
    restored.persist_reverb_listing_claim(*source('registered'))
    stats = restored.stats()
    assert stats['external_listing_sources'] == 2
    assert stats['registered_serial_listings'] == 1
    assert stats['serial_listing_coverage_percent'] == 50.0
    assert 'observations' not in stats
    assert restored.audit_observation_migration()['native_unregistered_crawl_rows'] == 1
