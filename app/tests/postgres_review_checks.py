"""End-to-end review and Owner transitions against disposable PostgreSQL only."""
import json
from dataclasses import replace
from psycopg import errors, sql
from ygc.cloud_applications import CloudApplications
from ygc.cloud_review import CloudReview, PrivatePhotoUnavailable
from ygc.cloud_owner import CloudOwner
from ygc.cloud_content_media import MediaConflict
from ygc.claim_revision import ClaimConflict
from ygc.db.postgres import connect
from test_cloud_avatar import png
from authentication_fixtures import transcription, comparison


def run(app, accounts, operations, store, aid, bid):
    def rejected(error, fn):
        try:
            fn()
        except error:
            return
        raise AssertionError('Expected ' + error.__name__)

    before = operations.details(aid)
    operations.set_mode(aid, mode='normal', message='', version=before['version'])
    bid = accounts.ensure_identity(issuer='review-fixture', subject='applicant', display_name='Review applicant')['app_user_id']
    accounts.drain_projection()
    intake, worker, owners = CloudApplications(app, operations, store), CloudReview(app, store), CloudOwner(app, operations)
    original_enabled = operations.review_status(aid)['enabled']
    operations.set_review(aid, enabled=False, expected_enabled=original_enabled)
    with connect(app, 'chronicle') as con:
        a = con.execute('SELECT id FROM users WHERE app_user_id=%s', (aid,)).fetchone()['id']
        b = con.execute('SELECT id FROM users WHERE app_user_id=%s', (bid,)).fetchone()['id']

    def submit(actor, serial=None, guitar=None):
        payload = dict(manufacturer='Fender', serial_number=serial, model='Tele', finish='', year='', occurred_at='2020-01-01', body='Review fixture')
        request = dict(kind='listing', payload=payload) if guitar is None else dict(kind='acquire', individual_id=str(guitar))
        row = intake.start(actor, request)
        for role in ('closeup', 'overview'):
            intake.upload(actor, row['revision'], role, png(), 'image/png')
        return intake.submit(actor, row['revision'], dict(acquisition_date='2020-01-01' if guitar is None else '2021-01-01', body=payload['body']))

    def claim(row):
        result = worker.call_tool('ygc_pending_' + row['kind'], {'remaining_revisions': [row['revision']]})
        assert row['serial'] not in json.dumps(result) and row['challenge'] not in json.dumps(result)
        return result['jobs'][0]

    def key(job):
        return {k: job[k] for k in ('revision', 'lease_token')}

    def observation(job):
        return key(job) | {'observations': {k: 'overview: unknown fixture feature' for k in ('maker', 'model', 'finish')}}

    def review(row, job):
        return key(job) | dict(closeup=transcription(row['serial'], row['challenge']),
            overview=transcription(None, row['challenge']), identity=comparison()['identity'] if job['reference_available'] else None,
            product_consistency={k: dict(status='uncertain', note='Cannot confirm; no contradiction.') for k in ('maker', 'model', 'finish')})

    listing = submit(aid, 'REVIEW001')
    assert worker.call_tool('ygc_pending_listing', {})['jobs'] == []
    rejected(PermissionError, lambda: operations.set_review(bid, enabled=True, expected_enabled=False))
    operations.set_review(aid, enabled=True, expected_enabled=False)
    job = claim(listing)
    assert worker.call_tool('ygc_pending_listing', {'remaining_revisions': [listing['revision']]})['jobs'] == []
    assert worker.call_tool('ygc_listing_image', key(job) | {'role': 'closeup'})['content'][0]['type'] == 'image'
    rejected(ValueError, lambda: worker.call_tool('ygc_acquire_image', key(job) | {'role': 'closeup'}))
    rejected(ValueError, lambda: worker.call_tool('ygc_submit_listing_review', review(listing, job)))
    worker.call_tool('ygc_listing_product_details', observation(job))
    rejected(ValueError, lambda: worker.call_tool('ygc_listing_product_details', key(job) | {'observations': dict(maker='changed', model='changed', finish='changed')}))
    owner_settings = replace(app, user='postgres')
    # A late notification failure rolls back individual, Claim and decision.
    with connect(owner_settings, 'chronicle') as con:
        con.execute(sql.SQL('REVOKE INSERT ON notifications FROM {}').format(sql.Identifier(app.user)))
    try:
        rejected(errors.InsufficientPrivilege, lambda: worker.call_tool('ygc_submit_listing_review', review(listing, job)))
    finally:
        with connect(owner_settings, 'chronicle') as con:
            con.execute(sql.SQL('GRANT INSERT ON notifications TO {}').format(sql.Identifier(app.user)))
    with connect(app, 'chronicle') as con:
        assert not con.execute("SELECT 1 FROM individuals WHERE normalized_serial='REVIEW001'").fetchone()
    result = worker.call_tool('ygc_submit_listing_review', review(listing, job))
    assert result['status'] == 'accepted'
    assert worker.call_tool('ygc_submit_listing_review', review(listing, job)) == result
    with connect(app, 'chronicle') as con:
        row = con.execute('SELECT * FROM acquire_applications WHERE revision=%s', (listing['revision'],)).fetchone()
        guitar = row['individual_id']
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (guitar,)).fetchone()['current_owner_user_id'] == a
        assert not con.execute('SELECT 1 FROM media_assets WHERE individual_id=%s', (guitar,)).fetchone()
    acquire = submit(bid, guitar=guitar)
    acquired_job = claim(acquire)
    assert acquired_job['reference_available']
    # OFF accepts and retains observations and result, never mutating Chronicle.
    operations.set_review(aid, enabled=False, expected_enabled=True)
    assert worker.call_tool('ygc_acquire_product_details', observation(acquired_job))['paused']
    assert worker.call_tool('ygc_submit_acquire_review', review(acquire, acquired_job))['applied'] is False
    with connect(app, 'chronicle') as con:
        row = con.execute('SELECT * FROM acquire_applications WHERE revision=%s', (acquire['revision'],)).fetchone()
        assert row['status'] == 'processing' and row['claim_id'] is None and row['product_observations'] is None
        con.execute('UPDATE acquire_applications SET lease_until=0 WHERE revision=%s', (acquire['revision'],))
    operations.set_review(aid, enabled=True, expected_enabled=False)
    worker.call_tool('ygc_pending_acquire', {'remaining_revisions': []})
    result = worker.call_tool('ygc_submit_acquire_review', review(acquire, acquired_job))
    assert result['status'] == 'accepted'
    claim_id = result['claim_id']
    with connect(app, 'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (guitar,)).fetchone()['current_owner_user_id'] == a
        assert con.execute('SELECT verification_status FROM claims WHERE id=%s', (claim_id,)).fetchone()['verification_status'] == 'unverified'
    visible = next(r for r in intake.list(bid)['items'] if r['revision']==acquire['revision'])
    assert visible['verification_status']=='unverified' and visible['claim_id']==str(claim_id) and visible['reasons']
    assert 'reference' not in visible and 'report' not in visible
    item = next(r for r in owners.pending(aid, guitar)['items'] if r['id'] == str(claim_id))
    rejected(ValueError, lambda: owners.respond(bid, guitar, claim_id, dict(stance='positive', revision=item['revision'])))
    assert owners.respond(aid, guitar, claim_id, dict(stance='positive', revision=item['revision']))['verification_status'] == 'positive'
    rejected(ClaimConflict, lambda: owners.respond(aid, guitar, claim_id, dict(stance='negative', revision=item['revision'])))
    with connect(app, 'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (guitar,)).fetchone()['current_owner_user_id'] == b
        states = {r['user_id']: r['ownership_status'] for r in con.execute('SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=%s', (guitar,))}
        assert states[a] == 'former_owner' and states[b] == 'current_owner'
    assert not owners.pending(aid, guitar)['items'] and not owners.pending(bid, guitar)['items']
    # Cancellation invalidates retained answers; expired leases rotate, with a
    # hard error after the third timeout. Photo-submission deadline is separate.
    cancelled = submit(bid, 'REVIEW002'); job = claim(cancelled)
    operations.set_review(aid, enabled=False, expected_enabled=True)
    worker.call_tool('ygc_listing_product_details', observation(job))
    worker.call_tool('ygc_submit_listing_review', review(cancelled, job))
    intake.cancel(bid, cancelled['revision'])
    operations.set_review(aid, enabled=True, expected_enabled=False)
    worker.call_tool('ygc_pending_listing', {'remaining_revisions': []})
    rejected(ValueError, lambda: worker.call_tool('ygc_submit_listing_review', review(cancelled, job)))
    timed = submit(bid, 'REVIEW003'); old = claim(timed)
    for attempt in range(3):
        with connect(app, 'chronicle') as con:
            con.execute('UPDATE acquire_applications SET lease_until=0 WHERE revision=%s', (timed['revision'],))
        queue = worker.call_tool('ygc_pending_listing', {'remaining_revisions': [timed['revision']]})
        if attempt < 2:
            assert queue['jobs'][0]['lease_token'] != old['lease_token']
        else:
            assert queue['jobs'] == []
    rejected(ValueError, lambda: worker.call_tool('ygc_listing_image', key(old) | {'role': 'overview'}))
    from ygc.cloud_guitars import GuitarMissing
    rejected(GuitarMissing, lambda: intake.retry(aid, timed['revision']))
    assert intake.retry(bid, timed['revision'])['status']=='pending'
    assert intake.retry(bid, timed['revision'])['status']=='pending'
    with connect(app, 'chronicle') as con:
        reset=con.execute('SELECT * FROM acquire_applications WHERE revision=%s',(timed['revision'],)).fetchone()
        assert reset['attempts']==0 and reset['lease_token'] is None and reset['product_observations'] is None
    new_attempt=claim(timed)
    rejected(ValueError, lambda: intake.retry(bid, timed['revision']))
    rejected(ValueError, lambda: worker.call_tool('ygc_listing_image', key(old) | {'role':'overview'}))
    intake.cancel(bid,timed['revision'])
    with connect(app, 'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        rejected(MediaConflict, lambda: worker.call_tool('ygc_pending_listing', {}))
    accounts.update_profile(bid, {'bio': 'Review stale projection'})
    rejected(ValueError, lambda: worker.call_tool('ygc_pending_listing', {}))
    accounts.drain_projection()
    # Submitted photo deadlines do not expire a queued application.
    restore_request = submit(bid, 'REVIEW004')
    with connect(app, 'chronicle') as con:
        con.execute('UPDATE acquire_applications SET expires_at=0 WHERE revision=%s', (restore_request['revision'],))
    restore_job = claim(restore_request)
    worker.call_tool('ygc_listing_product_details', observation(restore_job))
    # Missing a fixed-generation image is an operational failure, never an
    # absent-reference acceptance or partial Claim write.
    from ygc.cloud_applications import references
    from ygc.cloud_content_media import decode_reference
    with connect(app, 'chronicle') as con:
        stored = con.execute('SELECT * FROM acquire_applications WHERE revision=%s', (restore_request['revision'],)).fetchone()
    ref = decode_reference(references(stored)['closeup'])
    photo = store.objects.pop(ref)
    try:
        rejected(PrivatePhotoUnavailable, lambda: worker.call_tool('ygc_submit_listing_review', review(restore_request, restore_job)))
    finally:
        store.objects[ref] = photo
    # Real snapshot replacement must strip every restored lease, including the
    # one held by a still-running reviewer outside the database.
    from ygc.cloud_db_snapshot import snapshot
    from ygc.cloud_db_restore import load, replace_content
    data, metadata = snapshot(app, 'chronicle')
    header, rows, sequences = load(data, 'chronicle', metadata['sha256'])
    with connect(app, 'accounts') as source:
        current = list(source.execute('SELECT * FROM account_records'))
    with connect(app, 'chronicle') as con:
        replace_content(con, header, rows, sequences, current)
    rejected(ValueError, lambda: worker.call_tool('ygc_submit_listing_review', review(restore_request, restore_job)))
    fresh = claim(restore_request)
    assert fresh['lease_token'] != restore_job['lease_token']
    worker.call_tool('ygc_fail_listing', key(fresh) | {'reason': 'Fixture stopped'})
    # Two applicants can submit the same unregistered identity; only one may
    # create the Individual even when both already hold a lease.
    duplicate_a = submit(aid, 'REVIEW005'); duplicate_b = submit(bid, 'REVIEW005')
    job_a, job_b = claim(duplicate_a), claim(duplicate_b)
    for queued in (job_a, job_b):worker.call_tool('ygc_listing_product_details', observation(queued))
    assert worker.call_tool('ygc_submit_listing_review', review(duplicate_a, job_a))['status']=='accepted'
    assert worker.call_tool('ygc_submit_listing_review', review(duplicate_b, job_b))['status']=='closed'
    with connect(app, 'chronicle') as con:
        assert con.execute("SELECT COUNT(*) AS n FROM individuals WHERE normalized_serial='REVIEW005'").fetchone()['n']==1
    # A retained failure must revoke every old worker continuation, including
    # image reads; only an explicit applicant retry can issue a new lease.
    failed = submit(bid, 'REVIEW-PAUSED-FAIL'); failed_job = claim(failed)
    worker.call_tool('ygc_listing_product_details', observation(failed_job))
    operations.set_review(aid, enabled=False, expected_enabled=True)
    worker.call_tool('ygc_fail_listing', key(failed_job) | {'reason': 'Stopped while paused'})
    operations.set_review(aid, enabled=True, expected_enabled=False)
    rejected(ValueError, lambda: worker.call_tool('ygc_submit_listing_review', review(failed, failed_job)))
    rejected(ValueError, lambda: worker.call_tool('ygc_listing_product_details', observation(failed_job)))
    rejected(ValueError, lambda: worker.call_tool('ygc_listing_image', key(failed_job) | {'role': 'closeup'}))
    with connect(app, 'chronicle') as con:
        failed_state = con.execute('SELECT * FROM acquire_applications WHERE revision=%s', (failed['revision'],)).fetchone()
        assert failed_state['status'] == 'error' and failed_state['lease_token'] is None and failed_state['claim_id'] is None
    assert intake.retry(bid, failed['revision'])['status'] == 'pending'
    replacement = claim(failed)
    assert replacement['lease_token'] != failed_job['lease_token']
    worker.call_tool('ygc_fail_listing', key(replacement) | {'reason': 'Fixture stopped'})

    # One unavailable fixed-generation image cannot poison either queue.
    poisoned = submit(bid, 'REVIEW-PAUSED-PHOTO'); poisoned_job = claim(poisoned)
    operations.set_review(aid, enabled=False, expected_enabled=True)
    worker.call_tool('ygc_listing_product_details', observation(poisoned_job))
    worker.call_tool('ygc_submit_listing_review', review(poisoned, poisoned_job))
    with connect(app, 'chronicle') as con:
        poisoned_row = con.execute('SELECT * FROM acquire_applications WHERE revision=%s', (poisoned['revision'],)).fetchone()
    missing_ref = decode_reference(references(poisoned_row)['closeup'])
    missing_photo = store.objects.pop(missing_ref)
    good_listing = submit(bid, 'REVIEW-VALID-PHOTO')
    good_acquire = submit(aid, guitar=guitar)
    operations.set_review(aid, enabled=True, expected_enabled=False)
    try:
        good_acquire_job, good_listing_job = claim(good_acquire), claim(good_listing)
        with connect(app, 'chronicle') as con:
            stopped = con.execute('SELECT * FROM acquire_applications WHERE revision=%s', (poisoned['revision'],)).fetchone()
            assert stopped['status'] == 'error' and stopped['claim_id'] is None and stopped['lease_token'] is None
        with connect(app, 'operations') as con:
            assert not con.execute('SELECT 1 FROM paused_review_answers WHERE revision=%s', (poisoned['revision'],)).fetchone()
        worker.call_tool('ygc_fail_acquire', key(good_acquire_job) | {'reason': 'Fixture stopped'})
        worker.call_tool('ygc_fail_listing', key(good_listing_job) | {'reason': 'Fixture stopped'})
    finally:
        store.objects[missing_ref] = missing_photo

    # Initial selection quarantines a bad queue head before issuing any lease,
    # then reaches the next valid application in the same batch.
    bad_head, next_job = submit(bid, 'REVIEW-BAD-HEAD'), submit(bid, 'REVIEW-NEXT-HEAD')
    with connect(app, 'chronicle') as con:
        bad_row = con.execute('SELECT * FROM acquire_applications WHERE revision=%s', (bad_head['revision'],)).fetchone()
    missing_ref = decode_reference(references(bad_row)['overview'])
    missing_photo = store.objects.pop(missing_ref)
    try:
        found = worker.call_tool('ygc_pending_listing', {'remaining_revisions': [bad_head['revision'], next_job['revision']]})['jobs'][0]
        assert found['revision'] == next_job['revision']
        with connect(app, 'chronicle') as con:
            stopped = con.execute('SELECT * FROM acquire_applications WHERE revision=%s', (bad_head['revision'],)).fetchone()
            assert stopped['status'] == 'error' and stopped['attempts'] == 0 and stopped['lease_token'] is None
        worker.call_tool('ygc_fail_listing', key(found) | {'reason': 'Fixture stopped'})
    finally:
        store.objects[missing_ref] = missing_photo
    # Revocation is checked against canonical Accounts, not a cached token.
    revoked = submit(bid, 'REVIEW006'); revoked_job = claim(revoked)
    worker.call_tool('ygc_listing_product_details', observation(revoked_job))
    with connect(app, 'accounts') as con:
        con.execute('UPDATE account_records SET disabled=1 WHERE app_user_id=%s', (bid,))
    accounts.drain_projection()
    assert worker.call_tool('ygc_submit_listing_review', review(revoked, revoked_job))['status']=='closed'
    operations.set_review(aid, enabled=original_enabled, expected_enabled=True)
    state = operations.details(aid)
    operations.set_mode(aid, mode=before['mode'], message=before['message'], version=state['version'])
    print('PostgreSQL review: private Listing, Acquire, atomic rollback, immutable observations, OFF retention, cancellation, lease rotation, canonical projection, Owner transitions and idempotence passed.')
