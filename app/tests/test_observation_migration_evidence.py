"""The first migration phase copies source evidence without changing Individuals."""
import sqlite3
from pathlib import Path
import pytest

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
    decisions = repo.observation_diagnostic(first['individual_id'])['decisions']
    assert any(e['source_listing_id'] == '200' and e['date_basis'] == 'observed_at'
               for decision in decisions for e in decision['evidence'])


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


def test_evaluator_matches_migrated_snapshot_without_writing(tmp_path):
    source = Path(__file__).parent / 'data/ygc_test_snapshot.db'
    path = tmp_path / 'comparison.db'
    with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as old, sqlite3.connect(path) as target:
        old.backup(target)
    repo = Repository(path)
    repo.init_db()
    repo.migrate_legacy_observations_to_claims()
    repo.backfill_claim_source_evidence()
    repo.backfill_acquisition_date_evidence()
    with repo.connect() as con:
        ids = [row['id'] for row in con.execute('SELECT id FROM individuals ORDER BY id')]
        before = con.total_changes
    mismatches = {id: repo.observation_diagnostic(id)['differences'] for id in ids}
    assert ids and not {id: differences for id, differences in mismatches.items() if differences}
    audit = repo.audit_observation_migration()
    assert audit['individuals_checked'] == len(ids)
    assert audit['individuals_mismatched'] == audit['evaluation_errors'] == 0
    assert audit['marketplace_claims_without_evidence'] == 0
    with repo.connect() as con:
        assert con.total_changes == before == 0


def test_legacy_detail_cache_preserves_owner_fields_as_claim_evidence(tmp_path):
    repo = Repository(tmp_path / 'cache.db')
    repo.init_db()
    claim, provenance = _reverb_item('101')
    created = repo.persist_reverb_listing_claim(claim, provenance)
    with repo.connect() as con:
        con.execute('DELETE FROM claim_source_evidence')
        con.execute('INSERT OR REPLACE INTO crawl_detail_cache '
                    '(source_site,source_listing_id,payload_json,fetched_at) '
                    'VALUES (?,?,?,?)', ('reverb', '101', '{"raw":"listing"}',
                                          '2026-09-25T00:00:00+00:00'))
    assert repo.backfill_claim_source_evidence()['created'] == 1
    assert repo.observation_diagnostic(created['individual_id'])['differences'] == {}


def test_manual_acquire_requires_explicit_date_and_preserves_edited_evidence(tmp_path):
    repo = Repository(tmp_path / 'acquire.db')
    repo.init_db()
    owner = repo.create_user('Owner')
    individual_id, _, _, _ = repo.create_initial_listing_claim(
        owner, manufacturer='Fender', model='Telecaster', serial_number='DATE-001',
        media_storage_path='media/date.jpg', occurred_at='2020-01-01')
    with repo.connect() as con:
        initial_claims = con.execute('SELECT count(*) FROM claims').fetchone()[0]
    for value in (None, '', '2026-02-30', '2026-03-01T00:00:00Z'):
        try:
            repo.create_ownership_claim(owner, individual_id, ownership_kind='acquire',
                                        occurred_at=value)
        except ValueError as exc:
            assert 'Acquisition Date' in str(exc)
        else:
            raise AssertionError(f'Invalid acquisition date accepted: {value}')
    with repo.connect() as con:
        assert con.execute('SELECT count(*) FROM claims').fetchone()[0] == initial_claims

    _, claim_id = repo.create_ownership_claim(owner, individual_id, ownership_kind='acquire',
                                              occurred_at='2026-03-01')
    assert repo.observation_diagnostic(individual_id)['differences'] == {}
    assert repo.update_claim(claim_id, owner, occurred_at='2026-03-02')
    assert repo.update_claim(claim_id, owner, occurred_at='2026-03-03')
    with repo.connect() as con:
        rows = con.execute("""SELECT effective_date,date_basis FROM claim_source_evidence
                              WHERE claim_id=? AND evidence_type='acquisition_date'""",
                           (claim_id,)).fetchall()
        assert [tuple(row) for row in rows] == [('2026-03-03', 'user_reported')]
    assert repo.observation_diagnostic(individual_id)['differences'] == {}


def test_acquisition_date_backfill_uses_only_recorded_dates(tmp_path):
    repo = Repository(tmp_path / 'legacy-date.db')
    repo.init_db()
    owner = repo.create_user('Owner')
    individual_id, _, _, _ = repo.create_initial_listing_claim(
        owner, manufacturer='Fender', model='Telecaster', serial_number='DATE-002',
        media_storage_path='media/date2.jpg', occurred_at='2020-01-01')
    _, claim_id = repo.create_ownership_claim(owner, individual_id, ownership_kind='acquire',
                                              occurred_at='2026-03-01')
    with repo.connect() as con:
        con.execute('DELETE FROM claim_source_evidence WHERE claim_id=?', (claim_id,))
    assert repo.backfill_acquisition_date_evidence()['created'] == 1
    assert repo.backfill_acquisition_date_evidence()['existing'] == 1
    with repo.connect() as con:
        con.execute('DELETE FROM claim_source_evidence WHERE claim_id=?', (claim_id,))
        con.execute('UPDATE claims SET occurred_at=NULL WHERE id=?', (claim_id,))
    assert repo.backfill_acquisition_date_evidence()['missing_date'] == 1
    with repo.connect() as con:
        assert con.execute('SELECT count(*) FROM claim_source_evidence WHERE claim_id=?',
                           (claim_id,)).fetchone()[0] == 0


def test_diagnostic_endpoint_is_admin_only_and_read_only(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from ygc import config
    from ygc.web import app, CONSOLE_ADMIN_TOKEN

    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'api.db')
    repo = Repository(config.DB_PATH)
    repo.init_db()
    owner = repo.create_user('Owner')
    individual_id, _, _, _ = repo.create_initial_listing_claim(
        owner, manufacturer='Fender', model='Telecaster', serial_number='DIAG-001',
        media_storage_path='media/diag.jpg', occurred_at='2020-01-01')
    url = f'/api/admin/individuals/{individual_id}/observation-diagnostic'
    with repo.connect() as con:
        before = tuple(con.execute('SELECT * FROM individuals WHERE id=?', (individual_id,)).fetchone())
    with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 45000)) as client:
        assert client.get(url).status_code == 403
        response = client.get(url, headers={'X-YGC-Console-Admin': CONSOLE_ADMIN_TOKEN})
        assert response.status_code == 200
        assert response.json()['differences'] == {}
        assert response.json()['decisions']
        assert client.get('/api/admin/individuals/99999/observation-diagnostic',
                          headers={'X-YGC-Console-Admin': CONSOLE_ADMIN_TOKEN}).status_code == 404
    with repo.connect() as con:
        assert tuple(con.execute('SELECT * FROM individuals WHERE id=?', (individual_id,)).fetchone()) == before
    assert repo.audit_observation_migration()['individuals_mismatched'] == 0


def test_competing_acquire_waits_for_owner_and_never_appears_owned_early(tmp_path):
    repo = Repository(tmp_path / 'pending.db')
    repo.init_db()
    first_owner = repo.create_user('First')
    claimant = repo.create_user('Claimant')
    individual_id, _, _, _ = repo.create_initial_listing_claim(
        first_owner, manufacturer='Fender', model='Telecaster', serial_number='PENDING-001',
        media_storage_path='media/pending.jpg', occurred_at='2020-01-01')
    _, claim_id = repo.create_ownership_claim(
        claimant, individual_id, ownership_kind='acquire', occurred_at='2021-01-01')
    with repo.connect() as con:
        assert con.execute('SELECT verification_status FROM claims WHERE id=?',
                           (claim_id,)).fetchone()[0] == 'unverified'
    assert repo.get_user(claimant)[1] == []
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == first_owner
    assert repo.unverified_acquires()['total'] == 1
    try:
        repo.set_claim_response(claim_id, claimant, 'positive')
    except ValueError as exc:
        assert 'current owner' in str(exc)
    else:
        raise AssertionError('Claimant was able to self approve')
    assert repo.set_claim_response(claim_id, first_owner, 'positive')
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == claimant
    assert repo.get_user(claimant)[1][0]['ownership_status'] == 'current_owner'
    assert repo.get_user(first_owner)[1][0]['ownership_status'] == 'former_owner'
    assert repo.observation_diagnostic(individual_id)['differences'] == {}
    _, return_claim_id = repo.create_ownership_claim(
        first_owner, individual_id, ownership_kind='acquire', occurred_at='2022-01-01')
    return_claim = next(row for row in repo.list_claims(individual_id)
                        if row['id'] == return_claim_id)
    assert return_claim['verification_status'] == 'unverified'
    assert repo.get_user(first_owner)[1][0]['ownership_status'] == 'former_owner'
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == claimant
    try:
        repo.deactivate_claim(claim_id, claimant)
    except ValueError as exc:
        assert 'Current owner cannot deactivate' in str(exc)
    else:
        raise AssertionError('Current owner invalidated their own accepted Acquire')


def test_new_owner_can_verify_previous_owners_acquire_and_release(tmp_path):
    repo = Repository(tmp_path / 'owner-verification-after-transfer.db')
    repo.init_db()
    first_owner = repo.create_user('First')
    next_owner = repo.create_user('Next')
    individual_id, _, _, _ = repo.create_initial_listing_claim(
        first_owner, manufacturer='Fender', model='Telecaster', serial_number='TRANSFER-001',
        media_storage_path='media/transfer.jpg', occurred_at='2020-01-01')
    _, release_id = repo.create_ownership_claim(
        first_owner, individual_id, ownership_kind='release', occurred_at='2021-01-01')
    _, previous_acquire_id = repo.create_ownership_claim(
        first_owner, individual_id, ownership_kind='acquire', occurred_at='2022-01-01')
    repo.admin_moderate_claim(release_id, 'negative')
    _, next_acquire_id = repo.create_ownership_claim(
        next_owner, individual_id, ownership_kind='acquire', occurred_at='2023-01-01')
    assert repo.set_claim_response(next_acquire_id, first_owner, 'positive')
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == next_owner

    assert repo.set_claim_response(previous_acquire_id, next_owner, 'negative')
    assert repo.set_claim_response(release_id, next_owner, 'positive')
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == next_owner
    claims = {row['id']: row for row in repo.list_claims(individual_id)}
    assert claims[previous_acquire_id]['verification_status'] == 'negative'
    assert claims[release_id]['verification_status'] == 'positive'
    assert repo.observation_diagnostic(individual_id)['differences'] == {}
    try:
        repo.set_claim_response(previous_acquire_id, first_owner, 'positive')
    except ValueError as exc:
        assert 'current owner' in str(exc)
    else:
        raise AssertionError('Former owner verified an Acquire')


def test_return_acquire_waits_for_new_owner_across_profiles_and_claim_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from ygc import config
    from ygc.web import app

    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'return-acquire.db')
    repo = Repository(config.DB_PATH)
    repo.init_db()
    a = repo.create_user('A')
    b = repo.create_user('B')
    individual_id, _, listing_id, _ = repo.create_initial_listing_claim(
        a, manufacturer='Fender', model='Telecaster', serial_number='RETURN-001',
        media_storage_path='media/return.jpg', occurred_at='2020-01-01')
    _, b_claim = repo.create_ownership_claim(
        b, individual_id, ownership_kind='acquire', occurred_at='2022-01-01')
    assert repo.set_claim_response(b_claim, a, 'positive')

    with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 45000)) as client:
        for route in ('/user-view', f'/users/{a}', '/user-view/edit'):
            assert client.get(route).headers['cache-control'] == 'no-store'
        response = client.post(f'/api/individuals/{individual_id}/ownership-claim', json={
            'user_id': a, 'ownership_kind': 'acquire', 'occurred_at': '2023-01-01',
        })
        assert response.status_code == 200, response.text
        a_claim = response.json()['claim_id']
        a_profile = client.get(f'/api/users/{a}/profile?viewer_id={a}').json()
        b_profile = client.get(f'/api/users/{b}/profile?viewer_id={b}').json()
        assert next(g for g in a_profile['guitars'] if g['individual_id'] == individual_id)['ownership_status'] == 'former_owner'
        assert next(g for g in b_profile['guitars'] if g['individual_id'] == individual_id)['ownership_status'] == 'current_owner'
        for viewer in (a, b):
            detail = client.get(f'/api/individuals/{individual_id}?viewer_user_id={viewer}').json()
            assert int(detail['individual']['current_owner_user_id']) == b
        a_view = {c['id']: c for c in client.get(
            f'/api/individuals/{individual_id}/claims?viewer_user_id={a}').json()}
        b_view = {c['id']: c for c in client.get(
            f'/api/individuals/{individual_id}/claims?viewer_user_id={b}').json()}
        assert a_view[a_claim]['verification_status'] == 'unverified'
        assert not a_view[a_claim]['can_verify']
        assert b_view[a_claim]['can_verify']
        assert not b_view[b_claim]['can_verify']
        assert not b_view[listing_id]['can_verify']
        assert client.post(f'/api/claims/{a_claim}/response', json={
            'responder_user_id': a, 'stance': 'positive',
        }).status_code == 400
        assert client.post(f'/api/claims/{a_claim}/response', json={
            'responder_user_id': b, 'stance': 'positive',
        }).status_code == 200
        assert int(client.get(f'/api/individuals/{individual_id}').json()['individual']['current_owner_user_id']) == a
        assert not next(c for c in client.get(
            f'/api/individuals/{individual_id}/claims?viewer_user_id={a}').json()
            if c['id'] == a_claim)['can_verify']
        assert repo.observation_diagnostic(individual_id)['differences'] == {}


def test_restart_does_not_reclassify_verified_history_as_former_owner_pair(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from ygc import config
    from ygc.web import app

    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'restart.db')
    repo = Repository(config.DB_PATH)
    repo.init_db()
    first_owner = repo.create_user('First')
    next_owner = repo.create_user('Next')
    individual_id, _, _, _ = repo.create_initial_listing_claim(
        first_owner, manufacturer='Fender', model='Telecaster', serial_number='RESTART-001',
        media_storage_path='media/restart.jpg', occurred_at='2020-01-01')
    _, former_acquire_id = repo.create_ownership_claim(
        first_owner, individual_id, ownership_kind='acquire', occurred_at='2020-01-01')
    _, release_id = repo.create_ownership_claim(
        first_owner, individual_id, ownership_kind='release', occurred_at='2021-01-01')
    repo.admin_moderate_claim(release_id, 'negative')
    _, next_acquire_id = repo.create_ownership_claim(
        next_owner, individual_id, ownership_kind='acquire', occurred_at='2022-01-01')
    assert repo.set_claim_response(next_acquire_id, first_owner, 'positive')
    before = {row['id']: (row['ownership_source'], row['ownership_pair_id'],
                          row['verification_status']) for row in repo.list_claims(individual_id)}
    assert before[release_id][2] == 'negative'
    assert before[former_acquire_id][2] == 'positive'
    with repo.connect() as con:
        former_link = con.execute(
            "SELECT acquired_at, released_at FROM user_guitars WHERE user_id=? AND individual_id=?",
            (first_owner, individual_id),
        ).fetchone()
        assert former_link['acquired_at'][:10] == '2020-01-01'
        assert former_link['released_at'][:10] == '2021-01-01'
    with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 45000)) as client:
        # The web app calls init_db at startup; check the actual API payloads
        # consumed by the Claim cards, not just the repository's stored rows.
        a_claims = client.get(
            f'/api/individuals/{individual_id}/claims?viewer_user_id={first_owner}'
        ).json()
        b_claims = client.get(
            f'/api/individuals/{individual_id}/claims?viewer_user_id={next_owner}'
        ).json()
        by_a = {item['id']: item for item in a_claims}
        by_b = {item['id']: item for item in b_claims}
        assert not any(item['can_verify'] for item in a_claims)
        assert by_b[former_acquire_id]['can_verify']
        assert by_b[release_id]['can_verify']
        assert not by_b[next_acquire_id]['can_verify']
        assert not by_b[min(before)]['can_verify']  # Listing
        assert client.post(f'/api/claims/{release_id}/response', json={
            'responder_user_id': first_owner, 'stance': 'positive',
        }).status_code == 400
    repo.init_db()  # Repeated initialization must also leave decisions intact.
    after = {row['id']: (row['ownership_source'], row['ownership_pair_id'],
                         row['verification_status']) for row in repo.list_claims(individual_id)}
    assert after == before
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == next_owner

    # A database already affected by the old startup migration cannot regain
    # its previous decisions automatically. Its unrelated Claims must at
    # least remain independently verifiable instead of changing as a pair.
    with repo.connect() as con:
        con.execute(
            """UPDATE claims SET ownership_source='former_owner',
                 ownership_pair_id='incorrect-legacy-pair', verification_status='unverified'
                 WHERE id IN (?, ?)""",
            (former_acquire_id, release_id),
        )
    assert repo.set_claim_response(release_id, next_owner, 'positive')
    damaged = {row['id']: row for row in repo.list_claims(individual_id)}
    assert damaged[release_id]['verification_status'] == 'positive'
    assert damaged[former_acquire_id]['verification_status'] == 'unverified'
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == next_owner


def test_former_owner_stays_former_when_new_acquire_is_pending(tmp_path):
    repo = Repository(tmp_path / 'pending-return.db')
    repo.init_db()
    first_owner = repo.create_user('First')
    next_owner = repo.create_user('Next')
    individual_id, _, _, _ = repo.create_initial_listing_claim(
        first_owner, manufacturer='Fender', model='Telecaster', serial_number='RETURN-001',
        media_storage_path='media/return.jpg', occurred_at='2020-01-01')
    _, next_claim_id = repo.create_ownership_claim(
        next_owner, individual_id, ownership_kind='acquire', occurred_at='2022-01-01')
    assert repo.set_claim_response(next_claim_id, first_owner, 'positive')
    repo.create_ownership_claim(
        first_owner, individual_id, ownership_kind='acquire', occurred_at='2023-01-01')
    guitar = next(g for g in repo.get_user(first_owner)[1] if g['individual_id'] == individual_id)
    assert guitar['ownership_status'] == 'former_owner'
    assert repo.get_user_summary(first_owner)['former_count'] == 1


def test_unowned_acquires_same_day_use_first_claim_and_later_owner_confirmation(tmp_path):
    repo = Repository(tmp_path / 'same-day.db')
    repo.init_db()
    first = repo.persist_reverb_listing_claim(*_reverb_item('300'))
    first_owner = repo.create_user('First')
    second_owner = repo.create_user('Second')
    individual_id = first['individual_id']
    _, first_id = repo.create_ownership_claim(first_owner, individual_id,
                                              ownership_kind='acquire', occurred_at='2026-09-26')
    _, second_id = repo.create_ownership_claim(second_owner, individual_id,
                                               ownership_kind='acquire', occurred_at='2026-09-26')
    with repo.connect() as con:
        assert first_id < second_id
        assert [r[0] for r in con.execute(
            'SELECT verification_status FROM claims WHERE id IN (?,?) ORDER BY id',
            (first_id, second_id))] == ['positive', 'unverified']
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == first_owner
    assert repo.set_claim_response(second_id, first_owner, 'positive')
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == second_owner
    assert repo.observation_diagnostic(individual_id)['differences'] == {}


def test_earlier_acquire_entered_later_does_not_replace_later_owner(tmp_path):
    repo = Repository(tmp_path / 'backdate.db')
    repo.init_db()
    listing = repo.persist_reverb_listing_claim(*_reverb_item('400'))
    earlier = repo.create_user('Earlier')
    later = repo.create_user('Later')
    individual_id = listing['individual_id']
    repo.create_ownership_claim(later, individual_id, ownership_kind='acquire',
                                occurred_at='2026-09-27')
    _, backdated_id = repo.create_ownership_claim(earlier, individual_id,
                                                  ownership_kind='acquire', occurred_at='2026-09-26')
    with repo.connect() as con:
        assert con.execute('SELECT verification_status FROM claims WHERE id=?',
                           (backdated_id,)).fetchone()[0] == 'unverified'
    assert repo.set_claim_response(backdated_id, later, 'positive')
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == later
    assert repo.observation_diagnostic(individual_id)['differences'] == {}


def test_current_owner_can_redecide_admin_verification(tmp_path):
    repo = Repository(tmp_path / 'override.db')
    repo.init_db()
    first_owner = repo.create_user('First')
    claimant = repo.create_user('Claimant')
    individual_id, _, _, _ = repo.create_initial_listing_claim(
        first_owner, manufacturer='Fender', model='Telecaster', serial_number='OVERRIDE-001',
        media_storage_path='media/override.jpg', occurred_at='2020-01-01')
    _, claim_id = repo.create_ownership_claim(
        claimant, individual_id, ownership_kind='acquire', occurred_at='2021-01-01')
    repo.admin_moderate_claim(claim_id, 'negative')
    assert repo.set_claim_response(claim_id, first_owner, 'positive')
    with repo.connect() as con:
        verification = con.execute(
            'SELECT verification_status,admin_verification FROM claims WHERE id=?',
            (claim_id,),
        ).fetchone()
        assert tuple(verification) == ('positive', 0)
    assert int(repo.get_individual(individual_id)[0]['current_owner_user_id']) == claimant


def test_relisting_owner_is_rebuilt_from_evidence_without_legacy_observation(tmp_path):
    repo = Repository(tmp_path / 'evidence-only.db')
    repo.init_db()
    first = repo.persist_reverb_listing_claim(*_reverb_item('500'))
    claim, provenance = _reverb_item('501')
    claim['owner_name'] = 'New Shop'
    claim['location_region'] = 'NY'
    second = repo.persist_reverb_listing_claim(claim, provenance)
    individual_id = first['individual_id']
    assert second['individual_id'] == individual_id
    with repo.connect() as con:
        con.execute('DELETE FROM observations WHERE individual_id=?', (individual_id,))
        con.execute("""UPDATE individuals SET current_owner_name='Wrong',location_region='Wrong'
                       WHERE id=?""", (individual_id,))
    rebuilt = repo.rebuild_individual_snapshot(individual_id)
    assert rebuilt['current_owner_name'] == 'New Shop'
    assert rebuilt['location_region'] == 'NY'
    claims = repo.list_claims(individual_id)
    listing = next(row for row in claims if row['id'] == first['claim_id'])
    assert listing['source_site'] == 'reverb'
    assert listing['source_listing_id'] == '500'
    assert listing['source_url'] == 'https://example.test/500'
    acquire = next(row for row in claims if row['id'] == second['claim_id'])
    assert acquire['source_site'] == 'reverb'
    assert acquire['source_listing_id'] == '501'
    assert acquire['source_url'] == 'https://example.test/501'
    assert acquire['observation_raw_text'] == 'Serial 524436'
    assert repo.observation_diagnostic(individual_id)['differences'] == {}


def test_unavailable_listing_uses_evidence_after_old_crawl_row_is_removed(tmp_path):
    repo = Repository(tmp_path / 'unavailable.db')
    repo.init_db()
    listing = repo.persist_reverb_listing_claim(*_reverb_item('600'))
    with repo.connect() as con:
        con.execute('DELETE FROM observations WHERE individual_id=?',
                    (listing['individual_id'],))
    repeated = repo.persist_reverb_listing_claim(*_reverb_item('600'))
    assert repeated['created'] is False
    assert repeated['individual_id'] == listing['individual_id']
    result = repo.record_reverb_unavailable('600')
    assert result['created'] and result['owner_lost']
    assert repo.record_reverb_unavailable('600')['reason'] == 'already_recorded'
    with repo.connect() as con:
        release = con.execute('SELECT observation_id,target_claim_id FROM claims WHERE id=?',
                              (result['claim_id'],)).fetchone()
        assert release['observation_id'] is None
        assert release['target_claim_id'] == listing['claim_id']
    assert repo.get_individual(listing['individual_id'])[0]['current_owner_name'] == 'Unknown'
    assert repo.observation_diagnostic(listing['individual_id'])['differences'] == {}


def test_audit_does_not_create_a_missing_database(tmp_path):
    path = tmp_path / 'not-present.db'
    with pytest.raises(FileNotFoundError):
        Repository(path).audit_observation_migration()
    assert not path.exists()


def test_product_detail_image_comes_from_claim_evidence(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from ygc import config
    from ygc.web import app

    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'detail.db')
    repo = Repository(config.DB_PATH)
    repo.init_db()
    claim, provenance = _reverb_item('700')
    provenance['image_url'] = 'https://example.test/guitar.jpg'
    saved = repo.persist_reverb_listing_claim(claim, provenance)
    with repo.connect() as con:
        con.execute('DELETE FROM observations WHERE individual_id=?', (saved['individual_id'],))
    with TestClient(app) as client:
        response = client.get(f"/api/individuals/{saved['individual_id']}")
        assert response.status_code == 200
        detail = response.json()
        assert detail['observations'] == []
        assert detail['current_source']['image_url'] == provenance['image_url']
        assert detail['current_source']['source_listing_id'] == '700'


def test_materialized_owner_requires_matching_acquisition_date_evidence(tmp_path):
    repo = Repository(tmp_path / 'strict-owner.db')
    repo.init_db()
    initial = repo.create_user('Initial')
    claimant = repo.create_user('Claimant')
    individual_id, _, _, _ = repo.create_initial_listing_claim(
        initial, manufacturer='Fender', model='Telecaster', serial_number='STRICT-001',
        media_storage_path='media/strict.jpg', occurred_at='2020-01-01')
    with repo.connect() as con:
        claim_id = con.execute(
            """INSERT INTO claims (individual_id,author_user_id,claim_type,ownership_kind,
                                    value_text,occurred_at,created_at,updated_at)
               VALUES (?,?,'ownership','acquire',?,'2021-01-01','2021-01-02','2021-01-02')""",
            (individual_id, claimant, str(claimant)),
        ).lastrowid
    assert int(repo.rebuild_individual_snapshot(individual_id)['current_owner_user_id']) == initial
    with repo.connect() as con:
        con.execute(
            """INSERT INTO claim_source_evidence
               (claim_id,evidence_type,effective_date,date_basis,created_at)
               VALUES (?,'acquisition_date','2021-01-01','user_reported','2021-01-02')""",
            (claim_id,),
        )
    assert int(repo.rebuild_individual_snapshot(individual_id)['current_owner_user_id']) == claimant
    with repo.connect() as con:
        con.execute("UPDATE claims SET occurred_at='2021-01-03' WHERE id=?", (claim_id,))
    assert int(repo.rebuild_individual_snapshot(individual_id)['current_owner_user_id']) == initial
