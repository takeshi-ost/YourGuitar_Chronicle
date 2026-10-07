"""Event contracts on disposable loopback PostgreSQL, with synthetic photos.

Registered in run_postgres_checks.py. Import/compilation starts no server and
uses no real account, photo, cloud credential, or database. Fixtures and failure
injection use the database owner; every product operation uses the unchanged
restricted runtime role. Schema and grants are fingerprinted before/after.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
import json
import re
from threading import Barrier
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import psycopg
from psycopg import errors, sql

from postgres_media_claim_checks import (Storage, image_bytes, rejected,
    reject_new_rows, seed, seed_acquire, SNAPSHOT_TABLES, PUBLIC_FIELDS)
from ygc.admin_bootstrap_job import grant_first_admin
from ygc.claim_revision import ClaimConflict
from ygc.cloud_claim_routes import claim_router
from ygc.cloud_claims import CloudClaims
from ygc.cloud_content_media import decode_reference, encode_reference
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_owner import CloudOwner
from ygc.cloud_owner_routes import owner_router
from ygc.cloud_ownership import CloudOwnership
from ygc.cloud_public_catalog import CloudPublicCatalog
from ygc.db.postgres import PostgresSettings, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ServiceRestricted
from ygc.db.postgres_ownership import BoundRepository, PostgresOwnership
from ygc.db.postgres_queries import ObservationConnection
from ygc.identity_platform import VerifiedIdentity
from ygc.platform_boundaries import ActorContext

ISSUER = 'local-private-event-contract'
PRIVATE = 'EVENT-PRIVATE-DO-NOT-PUBLISH'
KINDS = ('exhibition', 'performance', 'recording', 'auction', 'other')
OWN_FIELDS = {'id', 'individual_id', 'claim_type', 'specification_kind',
              'incident_kind', 'event_kind', 'field_name', 'value_text', 'body',
              'occurred_at', 'status', 'verification_status', 'created_at',
              'updated_at', 'spec_items', 'revision', 'media_items'}
SNAPSHOT_FIELDS = ('manufacturer', 'model', 'serial_number', 'finish',
                   'location_country', 'location_region', 'current_owner_user_id')


def metadata(*, body=PRIVATE, date='2026-03-01', kind='performance'):
    return dict(claim_type='event', event_kind=kind, body=body, occurred_at=date)


def structure(settings, runtime):
    """Record existing schemas, versions and exact application table privileges."""
    result = {}
    for target in ('accounts', 'chronicle', 'operations'):
        with connect(settings, target) as con:
            result[target] = dict(
                versions=[dict(r) for r in con.execute('SELECT * FROM ygc_schema_version ORDER BY version')],
                columns=[dict(r) for r in con.execute("""SELECT table_name,column_name,
                    data_type,is_nullable,column_default FROM information_schema.columns
                    WHERE table_schema='public' ORDER BY table_name,ordinal_position""")],
                grants=[dict(r) for r in con.execute("""SELECT table_name,privilege_type,is_grantable
                    FROM information_schema.role_table_grants WHERE table_schema='public'
                    AND grantee=%s ORDER BY table_name,privilege_type""", (runtime,))],
                sequences=[dict(r) for r in con.execute("""SELECT sequence_name,data_type
                    FROM information_schema.sequences WHERE sequence_schema='public'
                    ORDER BY sequence_name""")])
    return result


def run(port):
    prefix = 'ygctest_event_claims_' + uuid.uuid4().hex[:10] + '_'
    runtime = prefix + 'app'
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port, prefix)
    app = replace(owner, user=runtime)
    databases = []
    with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='postgres',
                         password='ygc-tests-only', autocommit=True) as system:
        try:
            system.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(runtime), sql.Literal('ygc-tests-only')))
            for target in ('accounts', 'chronicle', 'operations'):
                name = owner.database(target)
                system.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                databases.append(name)
                bootstrap(owner, target, runtime)
                migrate(owner, target, runtime)
            before_structure = structure(owner, runtime)
            # No privilege expansion or migration is permitted for this unit.
            for target in ('accounts', 'chronicle', 'operations'):
                with connect(app, target) as con:
                    for query in ('CREATE TABLE event_forbidden(id BIGINT)',
                                  'UPDATE ygc_schema_version SET version=version'):
                        def forbidden():
                            with con.transaction():
                                con.execute(query)
                        rejected(errors.InsufficientPrivilege, forbidden)
            accounts, operations = PostgresAccounts(app), PostgresOperations(app)
            records = {name: accounts.ensure_identity(issuer=ISSUER, subject=name,
                display_name=PRIVATE + '-' + name) for name in ('admin', 'a', 'b', 'c')}
            admin = records['admin']['app_user_id']
            assert grant_first_admin(app, admin, 'local-event-test-operator')
            accounts.drain_projection()
            operations.set_mode(admin, mode='normal', message='',
                                version=operations.details(admin)['version'])
            storage = Storage()
            fixture = seed(owner, records, storage)
            # Reuse only synthetic identities/proof fixtures; this tombstone is
            # Event-specific, so its author remains able to find a hidden guitar.
            with connect(owner, 'chronicle') as con:
                con.execute("UPDATE claims SET claim_type='event',field_name='event_kind',"
                            "value_text='exhibition',body=%s WHERE id=%s",
                            (PRIVATE + '-inactive', fixture['hidden_claim']))
                # Establish the canonical Listing snapshot before asserting that
                # an Event leaves it unchanged; raw seed locations are not evidence.
                bound = BoundRepository(ObservationConnection(con))
                for individual in (fixture['individual'], fixture['other']):
                    bound._rebuild_individual_snapshot_in_connection(bound.connection, individual)
            checks(app, owner, accounts, operations, records, fixture, storage)
            assert structure(owner, runtime) == before_structure
            print('PostgreSQL Event Claims: JSON/text-only and optional private photos, '
                  'immutable kind/photos, complete revision-bound Owner content, '
                  'handoff/BAN fences, rollback and unknown commit, private transport, '
                  'service modes, public privacy and unchanged schema/grants passed.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))


def checks(settings, owner, accounts, operations, records, fixture, storage):
    service = CloudClaims(settings, operations, storage=storage)
    owners = CloudOwner(settings, operations)
    ownership = PostgresOwnership(settings)
    actors = {name: row['app_user_id'] for name, row in records.items()}
    individual = fixture['individual']
    uploads = [(image_bytes('PNG', (2400, 1200)), 'image/png'),
               (image_bytes('JPEG'), 'image/jpeg'), (image_bytes('WEBP'), 'image/webp')]

    def snapshot():
        with connect(settings, 'chronicle') as con:
            return {table: [dict(row) for row in con.execute(
                sql.SQL('SELECT * FROM {} ORDER BY id').format(sql.Identifier(table)))]
                for table in SNAPSHOT_TABLES}

    def current(name, claim, guitar=individual):
        return next(row for row in service.list(actors[name], guitar, limit=50)['items']
                    if row['id'] == str(claim))

    def pending(name, claim):
        return next(row for row in owners.pending(actors[name], individual)['items']
                    if row['id'] == str(claim))

    def create(name='b', *, images=None, kind='performance', body=PRIVATE, json_only=False):
        data = metadata(body=body, kind=kind)
        if json_only:
            assert images is None
            row = service.create(actors[name], individual, data)['claim']
        else:
            row = service.create_event(actors[name], individual, data,
                                       [] if images is None else images)['claim']
        assert set(row) == OWN_FIELDS and row['claim_type'] == 'event'
        assert row['event_kind'] == kind and row['value_text'] == kind
        assert row['field_name'] == 'event_kind' and row['spec_items'] == []
        assert row['specification_kind'] is None and row['incident_kind'] is None
        assert row['individual_id'] == str(individual) and int(row['id']) > 2**53
        assert re.fullmatch('[0-9a-f]{64}', row['revision'])
        assert len(row['media_items']) == len(images or [])
        assert all(set(m) == {'id', 'mime_type'} and m['mime_type'] == 'image/jpeg'
                   and int(m['id']) > 2**53 for m in row['media_items'])
        with connect(settings, 'chronicle') as con:
            saved = con.execute('SELECT * FROM claims WHERE id=%s', (int(row['id']),)).fetchone()
            assert saved['author_user_id'] == records[name]['id'] and saved['observation_id'] is None
            attached = con.execute('''SELECT e.id AS evidence_id,m.* FROM claim_evidence e
                JOIN media_assets m ON m.id=e.media_asset_id WHERE e.claim_id=%s ORDER BY e.id''',
                (int(row['id']),)).fetchall()
            assert [str(m['id']) for m in attached] == [m['id'] for m in row['media_items']]
            for asset in attached:
                assert asset['evidence_id'] > 2**53 and asset['uploader_user_id'] == records[name]['id']
                assert asset['individual_id'] == individual and asset['media_type'] == 'image'
                ref = decode_reference(asset['storage_path'])
                assert ref.scope == 'content' and ref.content_type == 'image/jpeg'
                with Image.open(BytesIO(storage.objects[ref])) as image:
                    assert image.format == 'JPEG' and max(image.size) <= 2048
                    assert image.mode == 'RGB' and not image.getexif()
        assert 'gcs-content-v1:' not in json.dumps(row) and 'storage_path' not in json.dumps(row)
        return row

    def photo(name, row, *, media=None, guitar=individual):
        return service.image(actors[name], guitar, int(row['id']),
            int(media or row['media_items'][0]['id']), row['revision'])

    def edit(name, row, *, body=PRIVATE + '-edited', date='2026-03-02'):
        return service.edit(actors[name], individual, int(row['id']),
            metadata(body=body, date=date, kind=row['event_kind']) | {'revision': row['revision']})['claim']

    def respond(name, row, stance='positive'):
        return owners.respond(actors[name], individual, int(row['id']),
                              dict(stance=stance, revision=row['revision']))

    # Five subtypes, both creation paths and the inclusive optional-photo range.
    before = snapshot()
    texts = [create('a', kind=kind, json_only=True) for kind in KINDS]
    assert all(row['verification_status'] == 'positive' and row['media_items'] == [] for row in texts)
    text_third = create('b', kind='other')
    owner_row = create('a', images=uploads, kind='exhibition')
    third = create('b', images=uploads, kind='recording')
    assert text_third['verification_status'] == third['verification_status'] == 'unverified'
    assert owner_row['verification_status'] == 'positive'
    assert len(snapshot()['notifications']) == len(before['notifications']) + 2
    assert not {m['id'] for m in owner_row['media_items']} & {m['id'] for m in third['media_items']}
    # Event means history only: neither text nor photos changes identity, owner,
    # location, profile classifications, or legacy Observation rows.
    after = snapshot()
    for old in before['individuals']:
        new = next(row for row in after['individuals'] if row['id'] == old['id'])
        assert {k: old[k] for k in SNAPSHOT_FIELDS} == {k: new[k] for k in SNAPSHOT_FIELDS}
    def classifications(state):
        return [(r['user_id'], r['individual_id'], r['ownership_status']) for r in state['user_guitars']]
    assert classifications(before) == classifications(after)
    assert before['observations'] == after['observations'] == []
    review = pending('a', third['id'])
    assert review['body'] == third['body'] and review['occurred_at'] == third['occurred_at']
    assert review['value_text'] == 'recording' and review['media_items'] == third['media_items']
    assert review['revision'] == third['revision']
    assert pending('a', text_third['id'])['media_items'] == []
    respond('a', pending('a', text_third['id']))
    assert photo('a', review) == photo('b', third)
    for name in ('c', 'admin'):
        fetched = list(storage.fetched)
        rejected(GuitarMissing, lambda: photo(name, third))
        assert storage.fetched == fetched
    for stance in ('positive', 'negative', 'unverified'):
        rejected(ValueError, lambda: respond('a', owner_row, stance))
        rejected(ValueError, lambda: respond('b', third, stance))
    for name in ('a', 'c', 'admin'):
        rejected(GuitarMissing, lambda: edit(name, third))
        rejected(GuitarMissing, lambda: service.deactivate(actors[name], individual,
            int(third['id']), {'revision': third['revision']}))
    assert service.list(actors['c'], individual)['items'] == []
    assert third['id'] not in {r['id'] for r in service.list(actors['a'], individual)['items']}
    rejected(GuitarMissing, lambda: photo('b', third, guitar=fixture['other']))
    rejected(GuitarMissing, lambda: photo('b', third, media=owner_row['media_items'][0]['id']))
    rejected(GuitarMissing, lambda: service.image(actors['a'], individual, fixture['listing'],
                                               fixture['proof'], owner_row['revision']))
    # A text-only Event has an explicit empty attachment set, never a fallback.
    rejected(GuitarMissing, lambda: photo('b', text_third, media=fixture['proof']))

    # Author edits preserve subtype/photos and both ordinary/admin decisions.
    changed = edit('b', third)
    assert changed['revision'] != third['revision'] and changed['media_items'] == third['media_items']
    assert changed['event_kind'] == third['event_kind']
    rejected(ClaimConflict, lambda: edit('b', third))
    rejected(ClaimConflict, lambda: photo('b', third))
    rejected(ClaimConflict, lambda: respond('a', review))
    for stance in ('positive', 'negative', 'unverified'):
        respond('a', pending('a', third['id']), stance)
        changed = edit('b', current('b', third['id']), body=PRIVATE + '-' + stance)
        assert changed['verification_status'] == stance and changed['media_items'] == third['media_items']
    principal = ActorContext(records['admin']['id'], 'identity-platform', None, True, actors['admin'])
    ownership.admin_moderate_claim(int(third['id']), principal, 'negative')
    changed = edit('b', current('b', third['id']), body=PRIVATE + '-admin-retained')
    assert changed['verification_status'] == 'negative'
    with connect(settings, 'chronicle') as con:
        assert con.execute('SELECT admin_verification FROM claims WHERE id=%s',
                           (int(third['id']),)).fetchone()['admin_verification'] == 1
    for data in (metadata(kind='auction'), dict(claim_type='incident', incident_kind='damage',
                    body=PRIVATE, occurred_at='2026-03-01')):
        rejected(ValueError, lambda: service.edit(actors['b'], individual, int(changed['id']),
                                                data | {'revision': changed['revision']}))
    attachment_checks(owner, service, owners, actors, individual, third, fixture, storage)
    third = current('b', third['id'])

    # Both paths require exact typed metadata, body and date; callers cannot
    # choose author/status, inject a storage reference, or mutate existing photos.
    invalid = [metadata(kind='unknown'), metadata(kind=None), metadata(body=None),
        metadata(body='  '), metadata(date=None), metadata(date=''), metadata(date='9999-01-01'),
        metadata() | {'media_items': []}, metadata() | {'storage_path': 'file:///private'},
        metadata() | {'author_user_id': records['a']['id']}, metadata() | {'verification_status': 'positive'}]
    for data in invalid:
        before, objects = snapshot(), dict(storage.objects)
        rejected(ValueError, lambda: service.create(actors['b'], individual, data))
        rejected(ValueError, lambda: service.create_event(actors['b'], individual, data, uploads))
        assert snapshot() == before and storage.objects == objects
    for images in (uploads * 4, [(b'broken', 'image/png')], [(uploads[0][0], 'image/jpeg')],
                   [(b'<svg/>', 'image/svg+xml')], [(image_bytes('PNG', (3000, 3000)), 'image/png')],
                   [(b'x' * (8 * 1024 * 1024 + 1), 'image/png')]):
        before, objects = snapshot(), dict(storage.objects)
        rejected(ValueError, lambda: service.create_event(actors['b'], individual, metadata(), images))
        assert snapshot() == before and storage.objects == objects
    create('b', images=[uploads[1]] * 10)

    # Legacy paths remain listed for private management but never get read from
    # disk or interpreted as URLs. They cannot masquerade as text-only Events.
    legacy = create('c', images=[uploads[1]])
    with connect(owner, 'chronicle') as con:
        con.execute('UPDATE media_assets SET storage_path=%s WHERE id=%s',
                    ('legacy/' + PRIVATE + '.jpg', int(legacy['media_items'][0]['id'])))
    legacy = current('c', legacy['id'])
    assert pending('a', legacy['id'])['media_items'] == legacy['media_items']
    fetched = list(storage.fetched)
    rejected(ValueError, lambda: photo('c', legacy))
    rejected(ValueError, lambda: photo('a', pending('a', legacy['id'])))
    rejected(ValueError, lambda: respond('a', pending('a', legacy['id'])))
    assert storage.fetched == fetched and 'legacy/' not in json.dumps(legacy)

    rollback_checks(owner, service, actors['b'], individual, storage, uploads, snapshot)
    retiring = current('b', third['id'])
    review = pending('a', retiring['id'])
    inactive = service.deactivate(actors['b'], individual, int(retiring['id']),
                                  {'revision': retiring['revision']})['claim']
    assert inactive['status'] == 'inactive' and inactive['media_items'] == retiring['media_items']
    assert inactive['event_kind'] == retiring['event_kind']
    assert inactive['verification_status'] == retiring['verification_status']
    assert current('b', inactive['id']) == inactive and photo('b', inactive)
    rejected(ClaimConflict, lambda: photo('b', retiring))
    rejected(GuitarMissing, lambda: photo('a', inactive))
    rejected(ClaimConflict, lambda: edit('b', inactive))
    rejected(ClaimConflict, lambda: respond('a', review))
    hidden = current('b', fixture['hidden_claim'], fixture['hidden'])
    assert hidden['event_kind'] == 'exhibition' and photo('b', hidden, guitar=fixture['hidden'])
    for name in ('a', 'admin'):
        rejected(GuitarMissing, lambda: service.list(actors[name], fixture['hidden']))
    for guitar in (fixture['absent'], 1234567):
        rejected(GuitarMissing, lambda: service.create_event(actors['b'], guitar, metadata(), uploads))
    full = service.list(actors['b'], individual, limit=50)['items']
    accumulated, after_id = [], 0
    while True:
        page = service.list(actors['b'], individual, limit=2, after=after_id)
        accumulated.extend(page['items'])
        if page['next_after'] is None:
            break
        after_id = int(page['next_after'])
        assert page['next_after'] == page['items'][-1]['id'] and len(accumulated) <= len(full)
    assert accumulated == full

    # Ownership, self-review, photo authority and profile classification move
    # together through the actual accepted Acquire/Observation transition.
    handoff = create('c', images=[uploads[1]])
    old_review = pending('a', handoff['id'])
    acquire = seed_acquire(owner, records['b']['id'], individual)
    respond('a', pending('a', acquire))
    with connect(settings, 'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',
                           (individual,)).fetchone()['current_owner_user_id'] == records['b']['id']
        classes = {r['user_id']: r['ownership_status'] for r in con.execute(
            'SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=%s', (individual,))}
        assert classes[records['a']['id']] == 'former_owner' and classes[records['b']['id']] == 'current_owner'
    rejected(GuitarMissing, lambda: photo('a', old_review))
    rejected(ValueError, lambda: respond('a', old_review))
    assert photo('b', pending('b', handoff['id'])) and photo('c', handoff)
    assert photo('a', current('a', owner_row['id']))
    assert create('a')['verification_status'] == 'unverified'
    assert create('b')['verification_status'] == 'positive'
    principal_b = ActorContext(records['b']['id'], 'identity-platform', None, True, actors['b'])
    for stance in ('positive', 'negative', 'unverified'):
        rejected(ValueError, lambda: ownership.set_claim_response(acquire, principal_b, stance))
    fence_checks(settings, owner, accounts, operations, records, service, owners,
                 individual, handoff, storage, uploads, snapshot)

    before, objects = snapshot(), dict(storage.objects)
    catalog = CloudPublicCatalog(settings, operations)
    public = catalog.chronicle(None, individual, limit=50)
    detail = catalog.detail(None, individual)
    assert detail['photo'] is None
    serialized = json.dumps([public, detail, catalog.list(None)])
    assert PRIVATE not in serialized and 'gcs-content-v1:' not in serialized
    for forbidden in ('media_items', 'storage_path', 'original_filename', 'event_kind', 'author_name'):
        assert forbidden not in serialized
    for row in public['items']:
        assert set(row) == PUBLIC_FIELDS
        if row['claim_type'] == 'event':
            assert row['items'] == [] and row['source_url'] is None
    assert inactive['id'] not in {r['id'] for r in public['items']}
    assert snapshot() == before and storage.objects == objects
    http_checks(owner, accounts, operations, records, service, owners, fixture, storage, uploads)

    # Two real runtime transactions start with the same complete revision. The
    # advisory fence or revision check must reject exactly one, never lose one
    # mutation behind another successful acknowledgement.
    racing = create('c', images=[uploads[1]], body=PRIVATE + '-race')
    reviewed = pending('b', racing['id'])
    gate = Barrier(2)
    def race(action):
        gate.wait(timeout=10)
        try:
            if action == 'edit':
                edit('c', racing, body=PRIVATE + '-race-edited')
            else:
                respond('b', reviewed)
            return action, 'accepted'
        except ClaimConflict:
            return action, 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(race, action) for action in ('edit', 'decision')]
        results = dict(future.result(timeout=20) for future in futures)
    assert sorted(results.values()) == ['accepted', 'conflict'], results
    fresh = current('c', racing['id'])
    assert fresh['revision'] != racing['revision'] and fresh['media_items'] == racing['media_items']
    if results['edit'] == 'accepted':
        assert fresh['body'] == PRIVATE + '-race-edited' and fresh['verification_status'] == 'unverified'
    else:
        assert fresh['body'] == PRIVATE + '-race' and fresh['verification_status'] == 'positive'
    rejected(ClaimConflict, lambda: photo('c', racing))

    # PR57's explicit Transfer acceptance must revoke Event review/photo access
    # as one property, independently of the Acquire approval journey above.
    transferred_event = create('a', images=[uploads[1]], kind='auction')
    retained_by_b = create('b', images=[uploads[1]], kind='exhibition')
    old_review = pending('b', transferred_event['id'])
    transfers = CloudOwnership(settings, operations)
    draft = transfers.create(actors['b'], individual, {
        'to_user_id': str(records['c']['id']),
        'revision': transfers.view(actors['b'], individual)['revision']})['transfer']
    assert draft['state'] == 'pending'
    assert photo('b', old_review)
    rejected(GuitarMissing, lambda: photo('c', transferred_event))
    recipient = transfers.detail(actors['c'], int(draft['id']))
    accepted = transfers.resolve(actors['c'], int(draft['id']), {
        'action': 'accept', 'revision': recipient['revision']})['transfer']
    assert accepted['state'] == 'accepted' and accepted['verification_status'] == 'positive'
    assert accepted['acceptance']['accepted_by_user_id'] == str(records['c']['id'])
    with connect(settings, 'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',
                           (individual,)).fetchone()['current_owner_user_id'] == records['c']['id']
        classes = {r['user_id']: r['ownership_status'] for r in con.execute(
            'SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=%s', (individual,))}
        assert classes[records['b']['id']] == 'former_owner' and classes[records['c']['id']] == 'current_owner'
    rejected(GuitarMissing, lambda: photo('b', old_review))
    rejected(ClaimConflict, lambda: respond('b', old_review))
    assert photo('c', pending('c', transferred_event['id'])) == photo('a', transferred_event)
    assert photo('b', current('b', retained_by_b['id']))
    principal_c = ActorContext(records['c']['id'], 'identity-platform', None, True, actors['c'])
    for stance in ('positive', 'negative', 'unverified'):
        rejected(ValueError, lambda: ownership.set_claim_response(int(draft['id']), principal_c, stance))


def attachment_checks(owner, service, owners, actors, individual, claim, fixture, storage):
    def own():
        return next(r for r in service.list(actors['b'], individual, limit=50)['items'] if r['id'] == claim['id'])
    def review():
        return next(r for r in owners.pending(actors['a'], individual)['items'] if r['id'] == claim['id'])
    def stale(before, old_review):
        after = own()
        assert after['updated_at'] == before['updated_at'] and after['revision'] != before['revision']
        rejected(ClaimConflict, lambda: service.edit(actors['b'], individual, int(claim['id']),
            metadata(kind=before['event_kind']) | {'revision': before['revision']}))
        rejected(ClaimConflict, lambda: owners.respond(actors['a'], individual, int(claim['id']),
            dict(stance='positive', revision=old_review['revision'])))
        rejected(ClaimConflict, lambda: service.image(actors['b'], individual, int(claim['id']),
            int(before['media_items'][0]['id']), before['revision']))
        return after
    for column, value in (('body', PRIVATE + '-same-timestamp'), ('value_text', 'auction'),
                          ('occurred_at', '2026-03-03')):
        before, old_review = own(), review()
        with connect(owner, 'chronicle') as con:
            con.execute(sql.SQL('UPDATE claims SET {}=%s WHERE id=%s').format(sql.Identifier(column)),
                        (value, int(claim['id'])))
        stale(before, old_review)
    before, old_review = own(), review()
    replacement = storage.put('content', image_bytes('JPEG', (60, 60)), content_type='image/jpeg')
    with connect(owner, 'chronicle') as con:
        con.execute('UPDATE media_assets SET storage_path=%s WHERE id=%s',
                    (encode_reference(replacement), int(before['media_items'][0]['id'])))
    after = stale(before, old_review)
    assert after['media_items'] == before['media_items']
    before, old_review = own(), review()
    with connect(owner, 'chronicle') as con:
        edge = con.execute('DELETE FROM claim_evidence WHERE claim_id=%s AND media_asset_id=%s '
                           'RETURNING media_asset_id,created_at',
                           (int(claim['id']), int(before['media_items'][-1]['id']))).fetchone()
        con.execute('INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(%s,%s,%s)',
                    (int(claim['id']), edge['media_asset_id'], edge['created_at']))
    assert stale(before, old_review)['media_items'] == before['media_items']
    before, old_review = own(), review()
    with connect(owner, 'chronicle') as con:
        con.execute('DELETE FROM claim_evidence WHERE claim_id=%s AND media_asset_id=%s',
                    (int(claim['id']), int(before['media_items'][-1]['id'])))
    assert len(stale(before, old_review)['media_items']) == len(before['media_items']) - 1
    # Existing ownership proof must not become reviewable just because someone
    # adds an evidence edge to Event. No storage fetch may occur.
    fetched = list(storage.fetched)
    with connect(owner, 'chronicle') as con:
        con.execute('INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(%s,%s,%s)',
                    (int(claim['id']), fixture['proof'], '2026-03-01'))
    try:
        rejected(GuitarMissing, lambda: service.image(actors['b'], individual, int(claim['id']),
            fixture['proof'], before['revision']))
        assert storage.fetched == fetched
    finally:
        with connect(owner, 'chronicle') as con:
            con.execute('DELETE FROM claim_evidence WHERE claim_id=%s AND media_asset_id=%s',
                        (int(claim['id']), fixture['proof']))


def rollback_checks(owner, service, actor, individual, storage, uploads, snapshot):
    for table in ('claims', 'media_assets', 'claim_evidence', 'notifications'):
        before, objects, deletes = snapshot(), dict(storage.objects), len(storage.deleted)
        with reject_new_rows(owner, table):
            rejected(errors.CheckViolation, lambda: service.create_event(actor, individual, metadata(), uploads))
        assert snapshot() == before and storage.objects == objects and len(storage.deleted) > deletes
    before, objects = snapshot(), dict(storage.objects)
    with reject_new_rows(owner, 'notifications'):
        rejected(errors.CheckViolation, lambda: service.create(actor, individual, metadata()))
    assert snapshot() == before and storage.objects == objects
    storage.fail_on = storage.put_calls + 2
    try:
        rejected(RuntimeError, lambda: service.create_event(actor, individual, metadata(), uploads))
    finally:
        storage.fail_on = None
    assert snapshot() == before and storage.objects == objects
    real_transaction = service.transaction
    @contextmanager
    def lost_acknowledgement(*args, **kwargs):
        with real_transaction(*args, **kwargs) as result:
            yield result
        raise RuntimeError('Synthetic lost Event commit acknowledgement')
    before, objects, deletes = snapshot(), set(storage.objects), list(storage.deleted)
    with patch.object(service, 'transaction', lost_acknowledgement):
        rejected(RuntimeError, lambda: service.create_event(actor, individual,
            metadata(body=PRIVATE + '-unknown-commit'), uploads))
    after = snapshot()
    assert len(after['claims']) == len(before['claims']) + 1
    assert len(after['notifications']) == len(before['notifications']) + 1
    retained = set(storage.objects) - objects
    assert len(retained) == len(uploads) and storage.deleted == deletes
    committed = next(row for row in after['claims'] if row['body'] == PRIVATE + '-unknown-commit')
    linked = {e['media_asset_id'] for e in after['claim_evidence'] if e['claim_id'] == committed['id']}
    assert {decode_reference(m['storage_path']) for m in after['media_assets'] if m['id'] in linked} == retained


def fence_checks(settings, owner, accounts, operations, records, service, owners,
                 individual, claim, storage, uploads, snapshot):
    actors = {name: row['app_user_id'] for name, row in records.items()}
    def image(name, row=claim):
        return service.image(actors[name], individual, int(row['id']),
                             int(row['media_items'][0]['id']), row['revision'])
    def create(name):
        return service.create_event(actors[name], individual, metadata(), uploads)['claim']
    def mode(value):
        operations.set_mode(actors['admin'], mode=value, message='',
                            version=operations.details(actors['admin'])['version'])
    for column, value, restore in (('disabled', 1, 0), ('ban_status', 'ban', 'normal'),
                                   ('account_type', 'source', 'user')):
        before, objects = snapshot(), dict(storage.objects)
        with connect(owner, 'accounts') as con:
            con.execute(sql.SQL('UPDATE account_records SET {}=%s WHERE app_user_id=%s')
                        .format(sql.Identifier(column)), (value, actors['c']))
        try:
            rejected(PermissionError, lambda: image('c'))
            rejected(PermissionError, lambda: service.list(actors['c'], individual))
            rejected(PermissionError, lambda: create('c'))
            assert snapshot() == before and storage.objects == objects
        finally:
            with connect(owner, 'accounts') as con:
                con.execute(sql.SQL('UPDATE account_records SET {}=%s WHERE app_user_id=%s')
                            .format(sql.Identifier(column)), (restore, actors['c']))
            accounts.drain_projection()
    with connect(owner, 'accounts') as con:
        con.execute("UPDATE account_records SET ban_status='ban' WHERE app_user_id=%s", (actors['c'],))
    accounts.drain_projection()
    try:
        rejected(GuitarMissing, lambda: image('b'))
        rejected(ClaimConflict, lambda: owners.respond(actors['b'], individual, int(claim['id']),
                                                      dict(stance='positive', revision=claim['revision'])))
        assert claim['id'] not in {r['id'] for r in owners.pending(actors['b'], individual)['items']}
    finally:
        with connect(owner, 'accounts') as con:
            con.execute("UPDATE account_records SET ban_status='normal' WHERE app_user_id=%s", (actors['c'],))
        accounts.drain_projection()
    accounts.update_profile(actors['a'], {'bio': PRIVATE + '-projection-pending'})
    for action in (lambda: image('c'), lambda: image('b'), lambda: create('b')):
        rejected(ValueError, action)
    accounts.drain_projection()
    assert image('b') and image('c')
    admin_claim = create('admin')
    mode('read_only')
    for name, row in (('c', claim), ('b', claim), ('admin', admin_claim)):
        assert image(name, row)
        assert service.list(actors[name], individual)['can_write'] is False
        assert owners.pending(actors[name], individual)['can_write'] is False
        rejected(ServiceRestricted, lambda: create(name))
        rejected(ServiceRestricted, lambda: service.create(actors[name], individual, metadata()))
    rejected(ServiceRestricted, lambda: service.edit(actors['admin'], individual, int(admin_claim['id']),
        metadata() | {'revision': admin_claim['revision']}))
    rejected(ServiceRestricted, lambda: service.deactivate(actors['admin'], individual, int(admin_claim['id']),
        {'revision': admin_claim['revision']}))
    rejected(ServiceRestricted, lambda: owners.respond(actors['b'], individual, int(claim['id']),
        dict(stance='positive', revision=claim['revision'])))
    mode('offline')
    for name, row in (('c', claim), ('b', claim), ('admin', admin_claim)):
        rejected(ServiceRestricted, lambda: image(name, row))
        rejected(ServiceRestricted, lambda: service.list(actors[name], individual))
        rejected(ServiceRestricted, lambda: create(name))
    mode('normal')
    before, objects = snapshot(), dict(storage.objects)
    with connect(settings, 'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        assert image('b') and image('c')
        rejected(ClaimConflict, lambda: create('b'))
    assert snapshot() == before and storage.objects == objects


def http_checks(owner, accounts, operations, records, service, owners, fixture, storage, uploads):
    from ygc.cloud_media_claim_routes import media_claim_router
    class Verifier:
        def __init__(self):
            self.accounts = accounts
        def verify(self, *, bearer_token):
            if bearer_token == 'unavailable':
                raise RuntimeError(PRIVATE)
            if bearer_token not in (*records, 'unverified'):
                raise PermissionError(PRIVATE)
            return VerifiedIdentity(ISSUER, 'c' if bearer_token == 'unverified' else bearer_token,
                                    '', bearer_token != 'unverified')
    api, verifier = FastAPI(), Verifier()
    api.include_router(claim_router(verifier, service))
    api.include_router(media_claim_router(verifier, service))
    api.include_router(owner_router(verifier, owners))
    base = '/api/auth/guitars/' + str(fixture['individual'])
    headers = lambda name: {'Authorization': 'Bearer ' + name}
    def parts(data=None, *, images=True):
        fields = [('metadata', (None, json.dumps(metadata() if data is None else data)))]
        return fields + ([('images', (PRIVATE + '.png', uploads[0][0], 'image/png'))] if images else [])
    def path(row):
        return base + '/claims/' + row['id'] + '/media/' + row['media_items'][0]['id']
    def private(response):
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Authorization'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['cross-origin-resource-policy'] == 'same-origin'
    with TestClient(api) as client:
        for name, code in ((None, 401), ('invalid', 401), ('unverified', 403), ('unavailable', 503)):
            auth = headers(name) if name else {}
            puts, fetched = storage.put_calls, list(storage.fetched)
            response = client.post(base + '/event-claims', headers=auth, files=parts())
            assert response.status_code == code and PRIVATE not in response.text
            private(response)
            assert client.post(base + '/claims', headers=auth, json=metadata()).status_code == code
            assert storage.put_calls == puts and storage.fetched == fetched
        # Optional attachments means valid multipart metadata alone, and JSON
        # creation uses the exact same Event payload and explicit empty array.
        for response in (client.post(base + '/claims', headers=headers('c'), json=metadata()),
                         client.post(base + '/event-claims', headers=headers('c'), files=parts(images=False))):
            assert response.status_code == 200, response.text
            assert response.json()['claim']['media_items'] == []
            assert response.json()['claim']['event_kind'] == 'performance'
        response = client.post(base + '/event-claims', headers=headers('c'), files=parts())
        assert response.status_code == 200, response.text
        private(response)
        row = response.json()['claim']
        assert set(row) == OWN_FIELDS and 'gcs-content-v1:' not in response.text
        assert PRIVATE + '.png' not in response.text
        for name in ('b', 'c'):
            response = client.get(path(row), headers=headers(name), params={'revision': row['revision']})
            assert response.status_code == 200 and response.headers['content-type'] == 'image/jpeg'
            private(response)
            with Image.open(BytesIO(response.content)) as image:
                assert image.format == 'JPEG' and image.size == (2048, 1024)
        for name in ('a', 'admin'):
            response = client.get(path(row), headers=headers(name), params={'revision': row['revision']})
            assert response.status_code == 404 and PRIVATE not in response.text
            private(response)
        for query in ('', '?revision=x', '?revision=' + row['revision'] + '&revision=' + row['revision'],
                      '?revision=' + row['revision'] + '&user_id=1'):
            assert client.get(path(row) + query, headers=headers('c')).status_code == 400
        invalid_forms = [parts() + [('unexpected', (None, PRIVATE))],
            parts() + [('metadata', (None, json.dumps(metadata())))],
            [('images', ('photo.png', uploads[0][0], 'image/png'))],
            [('metadata', ('metadata.json', json.dumps(metadata()), 'application/json'))],
            [('metadata', (None, json.dumps(metadata()))), ('images', (None, 'fake'))],
            parts(metadata(body='')), parts(metadata(date=None)), parts(metadata(kind='unknown')),
            parts(metadata() | {'media_items': []}), parts(metadata() | {'author_user_id': records['b']['id']}),
            [('metadata', (None, '{"claim_type":"event","claim_type":"event",'
                                '"event_kind":"other","body":"x","occurred_at":"2026-03-01"}'))]]
        for form in invalid_forms:
            puts = storage.put_calls
            response = client.post(base + '/event-claims', headers=headers('c'), files=form)
            assert response.status_code == 400 and storage.put_calls == puts, response.text
            private(response)
        for extra, code in (({'Origin': 'https://untrusted.invalid'}, 403),
                            ({'Sec-Fetch-Site': 'cross-site'}, 403),
                            ({'Content-Encoding': 'gzip'}, 400), ({'X-YGC-Timezone': 'Invalid/Zone'}, 400)):
            assert client.post(base + '/event-claims', headers=headers('c') | extra, files=parts()).status_code == code
        assert client.post(base + '/event-claims?author_user_id=1', headers=headers('c'), files=parts()).status_code == 400
        assert client.post(base + '/event-claims', headers=headers('c'), json=metadata()).status_code == 400
        assert client.post(base + '/media-claims', headers=headers('c'), files=parts()).status_code == 400
        too_many = parts(images=False) + [('images', ('photo.jpg', uploads[1][0], 'image/jpeg'))] * 11
        assert client.post(base + '/event-claims', headers=headers('c'), files=too_many).status_code == 400
        response = client.post(base + '/event-claims', headers=headers('c'), files=parts(images=False) +
            [('images', ('huge.png', b'x' * (8 * 1024 * 1024 + 1), 'image/png'))])
        assert response.status_code == 413 and response.json()['detail']['code'] == 'image_size_limit'
        private(response)
        old = row
        response = client.patch(base + '/claims/' + row['id'], headers=headers('c'),
            json=metadata(body=PRIVATE + '-http-edited') | {'revision': row['revision']})
        assert response.status_code == 200, response.text
        row = response.json()['claim']
        assert row['media_items'] == old['media_items'] and row['event_kind'] == old['event_kind']
        assert client.get(path(old), params={'revision': old['revision']}, headers=headers('c')).status_code == 409
        response = client.post(base + '/claims/' + row['id'] + '/deactivate', headers=headers('c'),
                               json={'revision': row['revision']})
        assert response.status_code == 200, response.text
        row = response.json()['claim']
        assert client.get(path(row), params={'revision': row['revision']}, headers=headers('c')).status_code == 200
        assert client.get(path(row), params={'revision': row['revision']}, headers=headers('b')).status_code == 404
