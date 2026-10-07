"""Private Media Claim contracts on disposable loopback PostgreSQL databases.

Registered in run_postgres_checks.py for an authorized developer machine or CI.
Import/compilation does not start PostgreSQL. All photos and account identities
are synthetic. The database owner seeds/tampers with fixtures; services use only
the unmodified restricted application role. No cloud or real/staging data is used.
"""
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
import json
import re
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import psycopg
from psycopg import errors, sql

from ygc.admin_bootstrap_job import grant_first_admin
from ygc.claim_revision import ClaimConflict
from ygc.cloud_claim_routes import claim_router
from ygc.cloud_claims import CloudClaims
from ygc.cloud_content_media import decode_reference, encode_reference
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_owner import CloudOwner
from ygc.cloud_owner_routes import owner_router
from ygc.cloud_public_catalog import CloudPublicCatalog
from ygc.cloud_storage import ObjectReference
from ygc.db.postgres import PostgresSettings, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ServiceRestricted
from ygc.db.postgres_ownership import PostgresOwnership
from ygc.identity_platform import VerifiedIdentity
from ygc.platform_boundaries import ActorContext

ISSUER = 'local-private-media-contract'
PRIVATE = 'MEDIA-PRIVATE-DO-NOT-PUBLISH'
BIG_ID = 9007199254741009
OWN_FIELDS = {'id', 'individual_id', 'claim_type', 'specification_kind',
              'incident_kind', 'field_name', 'value_text', 'body', 'occurred_at',
              'status', 'verification_status', 'created_at', 'updated_at',
              'spec_items', 'revision', 'media_items'}
PUBLIC_FIELDS = {'id', 'claim_type', 'ownership_kind', 'occurred_at', 'created_at',
                 'verification_status', 'items', 'source_url'}
SNAPSHOT_TABLES = ('claims', 'media_assets', 'claim_evidence', 'notifications',
                   'claim_responses', 'individuals', 'user_guitars', 'observations')


def rejected(error, operation):
    try:
        operation()
    except error:
        return
    raise AssertionError('Expected ' + error.__name__)


def image_bytes(kind='PNG', size=(80, 40)):
    out = BytesIO()
    with Image.new('RGB', size, (42, 77, 111)) as image:
        extra = {}
        if kind == 'JPEG':
            exif = image.getexif()
            exif[270] = PRIVATE
            extra['exif'] = exif
        image.save(out, format=kind, **extra)
    return out.getvalue()


def metadata(*, body=PRIVATE, date='2026-03-01'):
    return dict(claim_type='media', body=body, occurred_at=date)


class Storage:
    """In-memory immutable objects, with explicit partial-upload failure hooks."""
    def __init__(self):
        self.objects, self.deleted, self.fetched = {}, [], []
        self.put_calls, self.fail_on = 0, None

    def put(self, scope, data, *, content_type):
        self.put_calls += 1
        if self.put_calls == self.fail_on:
            raise RuntimeError('Synthetic storage failure')
        ref = ObjectReference(scope, 'media/' + format(self.put_calls, '032x'),
                              1, len(data), content_type)
        assert ref not in self.objects
        self.objects[ref] = data
        return ref

    def get(self, ref):
        self.fetched.append(ref)
        return self.objects[ref]

    def delete(self, ref):
        self.deleted.append(ref)
        del self.objects[ref]


@contextmanager
def reject_new_rows(owner, table):
    """Owner-only fault injection; never grants or expands runtime privileges."""
    name = 'synthetic_media_failure'
    with connect(owner, 'chronicle') as con:
        con.execute(sql.SQL('ALTER TABLE {} ADD CONSTRAINT {} CHECK (false) NOT VALID')
                    .format(sql.Identifier(table), sql.Identifier(name)))
    try:
        yield
    finally:
        with connect(owner, 'chronicle') as con:
            con.execute(sql.SQL('ALTER TABLE {} DROP CONSTRAINT {}')
                        .format(sql.Identifier(table), sql.Identifier(name)))


def run(port):
    prefix = 'ygctest_media_claims_' + uuid.uuid4().hex[:10] + '_'
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
            accounts, operations = PostgresAccounts(app), PostgresOperations(app)
            records = {name: accounts.ensure_identity(issuer=ISSUER, subject=name,
                display_name=PRIVATE + '-' + name) for name in ('admin', 'a', 'b', 'c')}
            admin = records['admin']['app_user_id']
            assert grant_first_admin(app, admin, 'local-test-operator')
            accounts.drain_projection()
            operations.set_mode(admin, mode='normal', message='',
                                version=operations.details(admin)['version'])
            storage = Storage()
            fixture = seed(owner, records, storage)
            # Media creation must not fall back to legacy Observation writes.
            with connect(owner, 'chronicle') as con:
                con.execute(sql.SQL('REVOKE INSERT,UPDATE,DELETE ON observations FROM {}')
                            .format(sql.Identifier(runtime)))
            checks(app, owner, accounts, operations, records, fixture, storage)
            print('PostgreSQL private Media Claims: shared inserts and exact IDs, '
                  'atomic evidence/notifications and storage compensation, private '
                  'revision-bound images, author/Owner/handoff fences, inactive '
                  'management, service modes, HTTP transport and public privacy passed.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))


def seed(owner, records, storage):
    with connect(owner, 'chronicle') as con:
        for individual in (BIG_ID, BIG_ID + 1, BIG_ID + 2, BIG_ID + 3):
            con.execute('''INSERT INTO individuals(id,manufacturer,model,serial_number,
                normalized_manufacturer,normalized_model,normalized_serial,
                location_country,location_region,current_owner_user_id,created_at,updated_at)
                VALUES(%s,'Fender','Telecaster',%s,'fender','telecaster',%s,%s,%s,%s,
                       '2026-01-01','2026-01-01')''',
                (individual, 'MEDIA-' + str(individual), str(individual), PRIVATE, PRIVATE,
                 records['a']['id'] if individual < BIG_ID + 2 else None))
        for table in ('claims', 'media_assets', 'claim_evidence'):
            con.execute('SELECT setval(pg_get_serial_sequence(%s,\'id\'),%s,false)',
                        (table, BIG_ID + 20))
        listings = []
        for individual in (BIG_ID, BIG_ID + 1):
            claim = con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,
                verification_status,occurred_at,created_at,updated_at)
                VALUES(%s,%s,'listing','positive','2026-01-01','2026-01-01','2026-01-01')
                RETURNING id''', (individual, records['a']['id'])).fetchone()['id']
            listings.append(claim)
            for field, value in (('manufacturer', 'Fender'), ('model', 'Telecaster'),
                    ('serial_number', 'MEDIA-' + str(individual)),
                    ('owner_user_id', str(records['a']['id']))):
                con.execute('''INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at)
                    VALUES(%s,%s,%s,'2026-01-01')''', (claim, field, value))
            con.execute('''INSERT INTO user_guitars(user_id,individual_id,ownership_status,
                created_at,updated_at) VALUES(%s,%s,'current_owner','2026-01-01','2026-01-01')''',
                (records['a']['id'], individual))
        inactive = con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,
            field_name,value_text,body,status,verification_status,occurred_at,created_at,updated_at)
            VALUES(%s,%s,'media','media_type','image',%s,'inactive','unverified',
                '2026-02-01','2026-02-01','2026-02-01') RETURNING id''',
            (BIG_ID + 2, records['b']['id'], PRIVATE)).fetchone()['id']
        def photo(individual, author, claim):
            ref = storage.put('content', image_bytes('JPEG'), content_type='image/jpeg')
            media = con.execute('''INSERT INTO media_assets(individual_id,uploader_user_id,
                storage_path,mime_type,captured_at,created_at,updated_at)
                VALUES(%s,%s,%s,'image/jpeg','2026-02-01','2026-02-01','2026-02-01')
                RETURNING id''', (individual, records[author]['id'], encode_reference(ref))).fetchone()['id']
            con.execute('INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(%s,%s,%s)',
                        (claim, media, '2026-02-01'))
            return media
        hidden_media = photo(BIG_ID + 2, 'b', inactive)
        proof = photo(BIG_ID, 'a', listings[0])
    return dict(individual=BIG_ID, other=BIG_ID + 1, hidden=BIG_ID + 2,
                absent=BIG_ID + 3, hidden_claim=inactive, hidden_media=hidden_media,
                listing=listings[0], proof=proof)


def checks(settings, db_owner, accounts, operations, records, fixture, storage):
    service = CloudClaims(settings, operations, storage=storage)
    owners, ownership = CloudOwner(settings, operations), PostgresOwnership(settings)
    catalog = CloudPublicCatalog(settings, operations)
    actors = {name: row['app_user_id'] for name, row in records.items()}
    individual = fixture['individual']
    uploads = [(image_bytes('PNG', (2400, 1200)), 'image/png'),
               (image_bytes('JPEG'), 'image/jpeg'), (image_bytes('WEBP'), 'image/webp')]

    def snapshot():
        with connect(settings, 'chronicle') as con:
            return {table: [dict(row) for row in con.execute(
                sql.SQL('SELECT * FROM {} ORDER BY id').format(sql.Identifier(table)))]
                for table in SNAPSHOT_TABLES}

    def own(name, claim, guitar=individual):
        return next(row for row in service.list(actors[name], guitar, limit=50)['items']
                    if row['id'] == str(claim))

    def pending(name, claim):
        return next(row for row in owners.pending(actors[name], individual)['items']
                    if row['id'] == str(claim))

    def create(name='b', data=None, images=None):
        row = service.create_media(actors[name], individual,
            metadata() if data is None else data, uploads if images is None else images)['claim']
        assert set(row) == OWN_FIELDS and row['claim_type'] == 'media'
        assert row['specification_kind'] is None and row['incident_kind'] is None
        assert row['spec_items'] == [] and row['field_name'] == 'media_type'
        assert row['value_text'] == 'image' and row['individual_id'] == str(individual)
        assert isinstance(row['id'], str) and int(row['id']) > 2**53
        assert re.fullmatch('[0-9a-f]{64}', row['revision'])
        with connect(settings, 'chronicle') as con:
            claim = con.execute('SELECT * FROM claims WHERE id=%s', (int(row['id']),)).fetchone()
            assert claim['author_user_id'] == records[name]['id'] and claim['observation_id'] is None
            attached = con.execute('''SELECT e.id AS evidence_id,m.* FROM claim_evidence e
                JOIN media_assets m ON m.id=e.media_asset_id WHERE e.claim_id=%s ORDER BY e.id''',
                (int(row['id']),)).fetchall()
            assert row['media_items'] == [dict(id=str(r['id']), mime_type='image/jpeg') for r in attached]
            for asset in attached:
                assert asset['id'] > 2**53 and asset['evidence_id'] > 2**53
                assert asset['uploader_user_id'] == records[name]['id']
                assert asset['individual_id'] == individual and asset['media_type'] == 'image'
                ref = decode_reference(asset['storage_path'])
                assert ref.scope == 'content' and ref.content_type == 'image/jpeg'
                with Image.open(BytesIO(storage.objects[ref])) as image:
                    assert image.format == 'JPEG' and max(image.size) <= 2048
                    assert not image.getexif() and image.mode == 'RGB'
        assert len(row['media_items']) == (len(uploads) if images is None else len(images))
        assert 'storage_path' not in json.dumps(row) and 'gcs-content-v1:' not in json.dumps(row)
        return row

    def photo(name, row, media=None, guitar=individual):
        return service.image(actors[name], guitar, int(row['id']),
            int(media if media is not None else row['media_items'][0]['id']), row['revision'])

    def edit(name, row, body=PRIVATE + '-edited'):
        return service.edit(actors[name], individual, int(row['id']),
                            metadata(body=body) | {'revision': row['revision']})['claim']

    def respond(name, row, stance):
        return owners.respond(actors[name], individual, int(row['id']),
                              dict(stance=stance, revision=row['revision']))

    # Real shared inserts: every image is new, IDs remain exact, and only the
    # non-owner post emits the ordinary owner notification in the transaction.
    owner_row = create('a')
    assert owner_row['verification_status'] == 'positive'
    third = create()
    assert third['verification_status'] == 'unverified'
    assert not {m['id'] for m in owner_row['media_items']} & {m['id'] for m in third['media_items']}
    review = pending('a', third['id'])
    assert review['media_items'] == third['media_items'] and review['revision'] == third['revision']
    with connect(settings, 'chronicle') as con:
        notices = con.execute("SELECT * FROM notifications WHERE notification_type='claim_added'").fetchall()
        assert len(notices) == 1 and notices[0]['claim_id'] == int(third['id'])
        assert notices[0]['recipient_user_id'] == records['a']['id']
        assert notices[0]['actor_user_id'] == records['b']['id']
    assert photo('b', third) == photo('a', review)
    assert photo('a', owner_row)
    for name in ('c', 'admin'):
        before_fetch = list(storage.fetched)
        rejected(GuitarMissing, lambda: photo(name, third))
        assert storage.fetched == before_fetch
    for stance in ('positive', 'negative', 'unverified'):
        rejected(ValueError, lambda: respond('a', owner_row, stance))
        rejected(ValueError, lambda: respond('b', third, stance))
    for name in ('a', 'c', 'admin'):
        rejected(GuitarMissing, lambda: edit(name, third))
        rejected(GuitarMissing, lambda: service.deactivate(actors[name], individual,
            int(third['id']), {'revision': third['revision']}))
    assert all(r['id'] != third['id'] for r in service.list(actors['a'], individual)['items'])
    assert service.list(actors['c'], individual)['items'] == []
    rejected(GuitarMissing, lambda: photo('b', third, guitar=fixture['other']))
    rejected(GuitarMissing, lambda: photo('b', third, media=owner_row['media_items'][0]['id']))
    rejected(GuitarMissing, lambda: photo('a', owner_row, media=fixture['proof']))
    rejected(GuitarMissing, lambda: service.image(actors['a'], individual, fixture['listing'],
                                               fixture['proof'], owner_row['revision']))

    # Metadata updates retain decisions, images and existing admin provenance.
    changed = edit('b', third)
    assert changed['revision'] != third['revision'] and changed['media_items'] == third['media_items']
    rejected(ClaimConflict, lambda: edit('b', third))
    rejected(ClaimConflict, lambda: photo('b', third))
    rejected(ClaimConflict, lambda: respond('a', review, 'positive'))
    for stance in ('positive', 'negative', 'unverified'):
        respond('a', pending('a', third['id']), stance)
        changed = edit('b', own('b', third['id']), PRIVATE + '-' + stance)
        assert changed['verification_status'] == stance
    principal = ActorContext(records['admin']['id'], 'identity-platform', None, True, actors['admin'])
    ownership.admin_moderate_claim(int(third['id']), principal, 'negative')
    changed = edit('b', own('b', third['id']), PRIVATE + '-admin-verdict-retained')
    assert changed['verification_status'] == 'negative'
    with connect(settings, 'chronicle') as con:
        assert con.execute('SELECT admin_verification FROM claims WHERE id=%s',
                           (int(third['id']),)).fetchone()['admin_verification'] == 1

    # The same Claim timestamp cannot mask metadata, attachment reference,
    # evidence-row identity or attachment-set changes from either confirmation.
    attachment_revision_checks(db_owner, service, owners, actors, individual, third, storage)
    third = own('b', third['id'])
    for bad in (metadata() | {'storage_path': 'file:///private'},
                metadata() | {'media_items': third['media_items']},
                metadata() | {'author_user_id': records['a']['id']},
                metadata(date='9999-01-01')):
        rejected(ValueError, lambda: service.create_media(actors['b'], individual, bad, uploads))
    rejected(ValueError, lambda: service.create(actors['b'], individual, metadata()))
    rejected(ValueError, lambda: service.edit(actors['b'], individual, int(third['id']),
        dict(claim_type='incident', incident_kind='damage', body=PRIVATE,
             occurred_at='2026-03-01', revision=third['revision'])))
    for invalid in ([], uploads * 4, [(b'broken', 'image/png')],
                    [(uploads[0][0], 'image/jpeg')], [(b'<svg/>', 'image/svg+xml')],
                    [(image_bytes('PNG', (3000, 3000)), 'image/png')],
                    [(b'x' * (8 * 1024 * 1024 + 1), 'image/png')]):
        before, objects = snapshot(), dict(storage.objects)
        rejected(ValueError, lambda: service.create_media(actors['b'], individual, metadata(), invalid))
        assert snapshot() == before and storage.objects == objects

    # A correct-looking evidence edge cannot turn a reused ownership/Listing
    # proof into an ordinary Media attachment, even for its original author.
    proof_isolation_checks(db_owner, service, actors, fixture, owner_row, storage)

    # Tombstones keep the author's private image access but revoke the Owner's.
    retiring = own('b', third['id'])
    review = pending('a', retiring['id'])
    inactive = service.deactivate(actors['b'], individual, int(retiring['id']),
                                 {'revision': retiring['revision']})['claim']
    assert inactive['status'] == 'inactive' and inactive['media_items'] == retiring['media_items']
    assert inactive['verification_status'] == retiring['verification_status']
    assert own('b', inactive['id']) == inactive and photo('b', inactive)
    rejected(ClaimConflict, lambda: photo('b', retiring))
    rejected(GuitarMissing, lambda: photo('a', inactive))
    rejected(ClaimConflict, lambda: edit('b', inactive))
    rejected(ClaimConflict, lambda: service.deactivate(actors['b'], individual,
        int(inactive['id']), {'revision': inactive['revision']}))
    rejected(ClaimConflict, lambda: respond('a', review, 'positive'))
    assert inactive['id'] not in {r['id'] for r in owners.pending(actors['a'], individual)['items']}
    hidden = own('b', fixture['hidden_claim'], fixture['hidden'])
    assert hidden['status'] == 'inactive' and photo('b', hidden, guitar=fixture['hidden'])
    for name in ('a', 'admin'):
        rejected(GuitarMissing, lambda: service.list(actors[name], fixture['hidden']))
        rejected(GuitarMissing, lambda: photo(name, hidden, guitar=fixture['hidden']))
    for guitar in (fixture['absent'], 1234567):
        rejected(GuitarMissing, lambda: service.create_media(actors['b'], guitar, metadata(), uploads))
    for bad_id in (0, -1, 2**63, True, '1'):
        rejected(ValueError, lambda: service.list(actors['b'], bad_id))

    rollback_checks(db_owner, service, actors['b'], individual, storage, uploads, snapshot)
    # Supported cap is inclusive and paging returns each private row once.
    create('b', images=[uploads[1]] * 10)
    full = service.list(actors['b'], individual, limit=50)['items']
    accumulated, after = [], 0
    while True:
        page = service.list(actors['b'], individual, limit=2, after=after)
        accumulated.extend(page['items'])
        if page['next_after'] is None:
            break
        after = int(page['next_after'])
        assert page['next_after'] == page['items'][-1]['id'] and len(accumulated) <= len(full)
    assert accumulated == full
    assert [int(r['id']) for r in full] == sorted({int(r['id']) for r in full}, reverse=True)

    # Acquire approval transfers image/decision authority together. Old Owner
    # retains its own Media, while new Owner cannot decide its own accepted root.
    handoff = create('c')
    owner_review = pending('a', handoff['id'])
    acquire = seed_acquire(db_owner, records['b']['id'], individual)
    respond('a', pending('a', acquire), 'positive')
    with connect(settings, 'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',
                           (individual,)).fetchone()['current_owner_user_id'] == records['b']['id']
        classifications = {r['user_id']: r['ownership_status'] for r in con.execute(
            'SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=%s', (individual,))}
        assert classifications[records['a']['id']] == 'former_owner'
        assert classifications[records['b']['id']] == 'current_owner'
    rejected(GuitarMissing, lambda: photo('a', owner_review))
    rejected(ValueError, lambda: respond('a', owner_review, 'positive'))
    assert photo('b', pending('b', handoff['id'])) and photo('c', handoff)
    assert photo('a', own('a', owner_row['id']))
    assert create('a')['verification_status'] == 'unverified'
    assert create('b')['verification_status'] == 'positive'
    principal_b = ActorContext(records['b']['id'], 'identity-platform', None, True, actors['b'])
    for stance in ('positive', 'negative', 'unverified'):
        rejected(ValueError, lambda: ownership.set_claim_response(acquire, principal_b, stance))

    fence_checks(settings, db_owner, accounts, operations, records, service, owners,
                 individual, handoff, storage, uploads, snapshot)

    # GETs do not repair projections, write audit/evidence, or publish private
    # prose, filenames, references, author/location data, or ownership photos.
    before, objects, deletes = snapshot(), dict(storage.objects), list(storage.deleted)
    assert photo('c', own('c', handoff['id']))
    assert photo('b', pending('b', handoff['id']))
    assert service.list(actors['b'], individual)['items']
    public = catalog.chronicle(None, individual, limit=50)
    detail = catalog.detail(None, individual)
    assert detail['photo'] is None
    serialized = json.dumps([public, detail, catalog.list(None)])
    assert PRIVATE not in serialized and 'gcs-content-v1:' not in serialized
    for forbidden in ('media_items', 'storage_path', 'original_filename', 'caption', 'image_meta'):
        assert forbidden not in serialized
    for row in public['items']:
        assert set(row) == PUBLIC_FIELDS
        if row['claim_type'] == 'media':
            assert row['items'] == [] and row['source_url'] is None
    assert inactive['id'] not in {r['id'] for r in public['items']}
    assert snapshot() == before and storage.objects == objects and storage.deleted == deletes
    assert not snapshot()['observations']
    http_checks(settings, db_owner, accounts, operations, records, service, owners,
                fixture, storage, uploads)


def attachment_revision_checks(owner, service, owners, actors, individual, claim, storage):
    def current():
        return next(r for r in service.list(actors['b'], individual, limit=50)['items']
                    if r['id'] == claim['id'])

    def review():
        return next(r for r in owners.pending(actors['a'], individual)['items']
                    if r['id'] == claim['id'])

    def assert_stale(before, owner_before):
        after = current()
        assert after['updated_at'] == before['updated_at']
        assert after['revision'] != before['revision']
        rejected(ClaimConflict, lambda: service.edit(actors['b'], individual, int(claim['id']),
            metadata() | {'revision': before['revision']}))
        rejected(ClaimConflict, lambda: owners.respond(actors['a'], individual, int(claim['id']),
            dict(stance='positive', revision=owner_before['revision'])))
        rejected(ClaimConflict, lambda: service.image(actors['b'], individual, int(claim['id']),
            int(before['media_items'][0]['id']), before['revision']))
        return after

    before, owner_before = current(), review()
    with connect(owner, 'chronicle') as con:
        con.execute('UPDATE claims SET body=%s WHERE id=%s',
                    (PRIVATE + '-same-timestamp', int(claim['id'])))
    assert_stale(before, owner_before)
    before, owner_before = current(), review()
    replacement = storage.put('content', image_bytes('JPEG', (60, 60)), content_type='image/jpeg')
    with connect(owner, 'chronicle') as con:
        con.execute('UPDATE media_assets SET storage_path=%s WHERE id=%s',
                    (encode_reference(replacement), int(before['media_items'][0]['id'])))
    after = assert_stale(before, owner_before)
    assert after['media_items'] == before['media_items']
    assert service.image(actors['b'], individual, int(claim['id']),
                         int(after['media_items'][0]['id']), after['revision']) == storage.objects[replacement]
    before, owner_before = current(), review()
    with connect(owner, 'chronicle') as con:
        edge = con.execute('DELETE FROM claim_evidence WHERE claim_id=%s AND media_asset_id=%s '
                           'RETURNING media_asset_id,created_at',
                           (int(claim['id']), int(before['media_items'][-1]['id']))).fetchone()
        con.execute('INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(%s,%s,%s)',
                    (int(claim['id']), edge['media_asset_id'], edge['created_at']))
    after = assert_stale(before, owner_before)
    assert after['media_items'] == before['media_items']
    before, owner_before = current(), review()
    removed = int(before['media_items'][-1]['id'])
    with connect(owner, 'chronicle') as con:
        con.execute('DELETE FROM claim_evidence WHERE claim_id=%s AND media_asset_id=%s',
                    (int(claim['id']), removed))
    after = assert_stale(before, owner_before)
    assert len(after['media_items']) == len(before['media_items']) - 1
    rejected(GuitarMissing, lambda: service.image(actors['b'], individual, int(claim['id']),
                                                removed, after['revision']))
    # A malformed storage locator remains private and is never passed to storage.
    media = int(after['media_items'][0]['id'])
    with connect(owner, 'chronicle') as con:
        original = con.execute('SELECT storage_path FROM media_assets WHERE id=%s', (media,)).fetchone()['storage_path']
        con.execute('UPDATE media_assets SET storage_path=%s WHERE id=%s', ('https://private.invalid/' + PRIVATE, media))
    try:
        row, fetched = current(), list(storage.fetched)
        rejected(ValueError, lambda: service.image(actors['b'], individual, int(claim['id']),
                                                  media, row['revision']))
        assert storage.fetched == fetched and PRIVATE not in json.dumps(row['media_items'])
    finally:
        with connect(owner, 'chronicle') as con:
            con.execute('UPDATE media_assets SET storage_path=%s WHERE id=%s', (original, media))


def proof_isolation_checks(owner, service, actors, fixture, claim, storage):
    individual, claim_id = fixture['individual'], int(claim['id'])
    fetched = list(storage.fetched)
    # Same uploader and guitar are insufficient when another Claim uses it as proof.
    with connect(owner, 'chronicle') as con:
        con.execute('INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(%s,%s,%s)',
                    (claim_id, fixture['proof'], '2026-02-01'))
    try:
        rejected(GuitarMissing, lambda: service.image(actors['a'], individual, claim_id,
                                                     fixture['proof'], claim['revision']))
        assert storage.fetched == fetched
    finally:
        with connect(owner, 'chronicle') as con:
            con.execute('DELETE FROM claim_evidence WHERE claim_id=%s AND media_asset_id=%s',
                        (claim_id, fixture['proof']))
    media = int(claim['media_items'][0]['id'])
    # Existing edges must also reject an asset moved to another guitar/uploader.
    for column, replacement in (('individual_id', fixture['other']),
                                ('uploader_user_id', None)):
        with connect(owner, 'chronicle') as con:
            original = con.execute(sql.SQL('SELECT {} FROM media_assets WHERE id=%s')
                                   .format(sql.Identifier(column)), (media,)).fetchone()[column]
            if replacement is None:
                replacement = con.execute('SELECT author_user_id FROM claims WHERE id=%s',
                                          (fixture['hidden_claim'],)).fetchone()['author_user_id']
            con.execute(sql.SQL('UPDATE media_assets SET {}=%s WHERE id=%s')
                        .format(sql.Identifier(column)), (replacement, media))
        try:
            rejected(GuitarMissing, lambda: service.image(actors['a'], individual, claim_id,
                                                         media, claim['revision']))
            assert storage.fetched == fetched
        finally:
            with connect(owner, 'chronicle') as con:
                con.execute(sql.SQL('UPDATE media_assets SET {}=%s WHERE id=%s')
                            .format(sql.Identifier(column)), (original, media))


def rollback_checks(owner, service, actor, individual, storage, uploads, snapshot):
    # Fail after storage creation at each real shared INSERT boundary. No partial
    # Claim/evidence/notification/snapshot rows or abandoned known objects survive.
    for table in ('media_assets', 'claim_evidence', 'notifications'):
        before, objects, deleted = snapshot(), dict(storage.objects), len(storage.deleted)
        with reject_new_rows(owner, table):
            rejected(errors.CheckViolation, lambda: service.create_media(actor, individual, metadata(), uploads))
        assert snapshot() == before and storage.objects == objects
        assert len(storage.deleted) > deleted
    before, objects, deleted = snapshot(), dict(storage.objects), len(storage.deleted)
    storage.fail_on = storage.put_calls + 2
    try:
        rejected(RuntimeError, lambda: service.create_media(actor, individual, metadata(), uploads))
    finally:
        storage.fail_on = None
    assert snapshot() == before and storage.objects == objects
    assert len(storage.deleted) == deleted + 1

    # Lose the acknowledgement after an actual successful PG commit. Retaining
    # objects is mandatory: deleting them would break the already committed Claim.
    real_transaction = service.transaction
    @contextmanager
    def lost_acknowledgement(*args, **kwargs):
        with real_transaction(*args, **kwargs) as result:
            yield result
        raise RuntimeError('Synthetic lost commit acknowledgement')
    before, objects, deleted = snapshot(), set(storage.objects), list(storage.deleted)
    with patch.object(service, 'transaction', lost_acknowledgement):
        rejected(RuntimeError, lambda: service.create_media(actor, individual,
            metadata(body=PRIVATE + '-committed-with-lost-ack'), uploads))
    after = snapshot()
    assert len(after['claims']) == len(before['claims']) + 1
    assert len(after['media_assets']) == len(before['media_assets']) + len(uploads)
    assert len(after['claim_evidence']) == len(before['claim_evidence']) + len(uploads)
    assert len(after['notifications']) == len(before['notifications']) + 1
    retained = set(storage.objects) - objects
    assert len(retained) == len(uploads) and storage.deleted == deleted
    committed = next(r for r in after['claims'] if r['body'] == PRIVATE + '-committed-with-lost-ack')
    linked = {e['media_asset_id'] for e in after['claim_evidence'] if e['claim_id'] == committed['id']}
    assert {decode_reference(m['storage_path']) for m in after['media_assets'] if m['id'] in linked} == retained


def seed_acquire(owner, user, individual):
    with connect(owner, 'chronicle') as con:
        old_owner = con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',
                                (individual,)).fetchone()['current_owner_user_id']
        acquire = con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,
            ownership_kind,ownership_source,value_text,verification_status,occurred_at,created_at,updated_at)
            VALUES(%s,%s,'ownership','acquire','user',%s,'unverified','2026-04-01','2026-04-01','2026-04-01')
            RETURNING id''', (individual, user, str(user))).fetchone()['id']
        con.execute('''INSERT INTO claim_source_evidence(claim_id,evidence_type,effective_date,created_at)
            VALUES(%s,'acquisition_date','2026-04-01','2026-04-01')''', (acquire,))
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s',
                           (individual,)).fetchone()['current_owner_user_id'] == old_owner
        assert not con.execute('SELECT 1 FROM user_guitars WHERE individual_id=%s AND user_id=%s',
                               (individual, user)).fetchone()
    return acquire


def fence_checks(settings, owner, accounts, operations, records, service, owners,
                 individual, claim, storage, uploads, snapshot):
    actors = {name: row['app_user_id'] for name, row in records.items()}
    def image(name, row=claim):
        return service.image(actors[name], individual, int(row['id']),
                             int(row['media_items'][0]['id']), row['revision'])
    def create(name):
        return service.create_media(actors[name], individual, metadata(), uploads)['claim']
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
    # A projected author BAN also revokes normal Owner access to that Claim.
    with connect(owner, 'accounts') as con:
        con.execute("UPDATE account_records SET ban_status='ban' WHERE app_user_id=%s", (actors['c'],))
    accounts.drain_projection()
    try:
        rejected(GuitarMissing, lambda: image('b'))
        assert claim['id'] not in {r['id'] for r in owners.pending(actors['b'], individual)['items']}
    finally:
        with connect(owner, 'accounts') as con:
            con.execute("UPDATE account_records SET ban_status='normal' WHERE app_user_id=%s", (actors['c'],))
        accounts.drain_projection()
    accounts.update_profile(actors['a'], {'bio': PRIVATE + '-undelivered-projection'})
    before, objects = snapshot(), dict(storage.objects)
    for action in (lambda: image('c'), lambda: image('b'), lambda: create('b'),
                   lambda: service.list(actors['c'], individual)):
        rejected(ValueError, action)
    assert snapshot() == before and storage.objects == objects
    accounts.drain_projection()
    assert image('b') and image('c')

    admin_claim = create('admin')
    mode('read_only')
    for name, row in (('c', claim), ('b', claim), ('admin', admin_claim)):
        assert image(name, row)
        assert service.list(actors[name], individual)['can_write'] is False
        assert owners.pending(actors[name], individual)['can_write'] is False
        rejected(ServiceRestricted, lambda: create(name))
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
    mode('admin_only')
    for name in ('b', 'c'):
        rejected(ServiceRestricted, lambda: image(name))
        rejected(ServiceRestricted, lambda: create(name))
    assert image('admin', admin_claim) and create('admin')
    rejected(GuitarMissing, lambda: image('admin'))
    with connect(owner, 'accounts') as con:
        con.execute("UPDATE account_records SET role='member' WHERE app_user_id=%s", (actors['admin'],))
    try:
        rejected(ServiceRestricted, lambda: image('admin', admin_claim))
        rejected(ServiceRestricted, lambda: create('admin'))
    finally:
        with connect(owner, 'accounts') as con:
            con.execute("UPDATE account_records SET role='admin' WHERE app_user_id=%s", (actors['admin'],))
        accounts.drain_projection()
        mode('normal')
    before, objects = snapshot(), dict(storage.objects)
    with connect(settings, 'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        assert image('b') and image('c')
        rejected(ClaimConflict, lambda: create('b'))
    assert snapshot() == before and storage.objects == objects


def http_checks(settings, owner, accounts, operations, records, service, owners,
                fixture, storage, uploads):
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

    from ygc.cloud_media_claim_routes import media_claim_router
    api = FastAPI()
    verifier = Verifier()
    api.include_router(claim_router(verifier, service))
    api.include_router(media_claim_router(verifier, service))
    api.include_router(owner_router(verifier, owners))
    individual = fixture['individual']
    base = f'/api/auth/guitars/{individual}'
    headers = lambda name: {'Authorization': 'Bearer ' + name}
    def parts(data=None):
        return [('metadata', (None, json.dumps(metadata() if data is None else data))),
                ('images', (PRIVATE + '.png', uploads[0][0], 'image/png'))]
    def path(row, media=None):
        return base + '/claims/' + row['id'] + '/media/' + str(
            row['media_items'][0]['id'] if media is None else media)
    def private(response):
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Authorization'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['cross-origin-resource-policy'] == 'same-origin'

    with TestClient(api) as client:
        for name, code in ((None, 401), ('invalid', 401), ('unverified', 403), ('unavailable', 503)):
            auth = headers(name) if name else {}
            puts, fetched = storage.put_calls, list(storage.fetched)
            response = client.post(base + '/media-claims', headers=auth, files=parts())
            assert response.status_code == code and PRIVATE not in response.text
            private(response)
            image = client.get(base + '/claims/1/media/1?revision=' + 'a' * 64, headers=auth)
            assert image.status_code == code and PRIVATE not in image.text
            private(image)
            assert storage.put_calls == puts and storage.fetched == fetched
        response = client.post(base + '/media-claims', headers=headers('c'), files=parts())
        assert response.status_code == 200, response.text
        private(response)
        row = response.json()['claim']
        assert set(row) == OWN_FIELDS
        assert all(set(m) == {'id', 'mime_type'} for m in row['media_items'])
        assert all(m['mime_type'] == 'image/jpeg' for m in row['media_items'])
        assert 'gcs-content-v1:' not in response.text and PRIVATE + '.png' not in response.text
        for name in ('b', 'c'):
            response = client.get(path(row), params={'revision': row['revision']}, headers=headers(name))
            assert response.status_code == 200 and response.headers['content-type'] == 'image/jpeg'
            private(response)
            with Image.open(BytesIO(response.content)) as image:
                assert image.format == 'JPEG' and image.size == (2048, 1024)
        for name in ('a', 'admin'):
            response = client.get(path(row), params={'revision': row['revision']}, headers=headers(name))
            assert response.status_code == 404 and PRIVATE not in response.text
            private(response)
        for query in ('', '?revision=x', '?revision=' + row['revision'] + '&revision=' + row['revision'],
                      '?revision=' + row['revision'] + '&user_id=1',
                      '?revision=' + row['revision'] + '&storage_path=' + PRIVATE):
            response = client.get(path(row) + query, headers=headers('c'))
            assert response.status_code == 400 and PRIVATE not in response.text
            private(response)
        for identifier, code in (('0', 400), ('-1', 400), ('1.0', 400), (str(2**63), 400),
                                 ('1234567', 404), (str(fixture['absent']), 404)):
            bad_base = f'/api/auth/guitars/{identifier}'
            response = client.post(bad_base + '/media-claims', headers=headers('c'), files=parts())
            assert response.status_code == code, response.text
            private(response)
            response = client.get(bad_base + '/claims/' + row['id'] + '/media/' + row['media_items'][0]['id'],
                                  params={'revision': row['revision']}, headers=headers('c'))
            assert response.status_code == code, response.text
        for claim_id, asset_id, code in ((row['id'], str(fixture['proof']), 404),
                (str(fixture['listing']), str(fixture['proof']), 404),
                (row['id'], '0', 400), ('0', row['media_items'][0]['id'], 400)):
            url = base + '/claims/' + claim_id + '/media/' + asset_id
            assert client.get(url, params={'revision': row['revision']},
                              headers=headers('c')).status_code == code
        # Multipart accepts exactly one text metadata field and repeated uploads.
        invalid_forms = [parts() + [('unexpected', (None, PRIVATE))],
                         parts() + [('metadata', (None, json.dumps(metadata())))],
                         [('images', ('photo.png', uploads[0][0], 'image/png'))],
                         [('metadata', (None, json.dumps(metadata())))],
                         [('metadata', ('metadata.json', json.dumps(metadata()), 'application/json')),
                          ('images', ('photo.png', uploads[0][0], 'image/png'))],
                         [('metadata', (None, json.dumps(metadata()))), ('images', (None, 'fake'))],
                         parts(metadata() | {'media_items': row['media_items']}),
                         parts(metadata() | {'author_user_id': records['b']['id']}),
                         parts(metadata(date='9999-01-01')),
                         [('metadata', (None, '{"claim_type":"media","claim_type":"media",'
                                             '"body":null,"occurred_at":"2026-03-01"}')),
                          ('images', ('photo.png', uploads[0][0], 'image/png'))]]
        for form in invalid_forms:
            puts = storage.put_calls
            response = client.post(base + '/media-claims', headers=headers('c'), files=form)
            assert response.status_code == 400 and storage.put_calls == puts, response.text
            private(response)
        for extra, code in (({'Origin': 'https://untrusted.invalid'}, 403),
                            ({'Sec-Fetch-Site': 'cross-site'}, 403),
                            ({'Content-Encoding': 'gzip'}, 400),
                            ({'X-YGC-Timezone': 'Invalid/Zone'}, 400)):
            assert client.post(base + '/media-claims', headers=headers('c') | extra,
                               files=parts()).status_code == code
        assert client.post(base + '/media-claims?author_user_id=1', headers=headers('c'), files=parts()).status_code == 400
        assert client.post(base + '/media-claims', headers=headers('c'), json=metadata()).status_code == 400
        assert client.post(base + '/claims', headers=headers('c'), json=metadata()).status_code == 400
        too_many = [('metadata', (None, json.dumps(metadata())))] + [
            ('images', ('photo.jpg', uploads[1][0], 'image/jpeg'))] * 11
        assert client.post(base + '/media-claims', headers=headers('c'), files=too_many).status_code == 400
        for duplicated in ([('Authorization', 'Bearer c'), ('Authorization', 'Bearer c')],
                           [('Authorization', 'Bearer c'), ('Authorization', 'Bearer admin')]):
            assert client.get(path(row), params={'revision': row['revision']},
                              headers=duplicated).status_code in (400, 401)
        response = client.post(base + '/media-claims', headers=headers('c'), files=[
            ('metadata', (None, json.dumps(metadata()))),
            ('images', ('huge.png', b'x' * (8 * 1024 * 1024 + 1), 'image/png'))])
        assert response.status_code == 413 and response.json()['detail']['code'] == 'image_size_limit'
        private(response)
        for data, mime, code in ((b'broken', 'image/png', 'invalid_image'),
                                 (uploads[0][0], 'image/jpeg', 'image_format')):
            response = client.post(base + '/media-claims', headers=headers('c'), files=[
                ('metadata', (None, json.dumps(metadata()))), ('images', ('image', data, mime))])
            assert response.status_code == 400 and response.json()['detail']['code'] == code

        # Photo requests bind to current metadata and remain private after the
        # author retires the Claim; normal Owner permission disappears at once.
        old = row
        response = client.patch(base + '/claims/' + row['id'], headers=headers('c'),
            json=metadata(body=PRIVATE + '-http-edited') | {'revision': row['revision']})
        assert response.status_code == 200, response.text
        row = response.json()['claim']
        assert client.get(path(old), params={'revision': old['revision']}, headers=headers('c')).status_code == 409
        response = client.post(base + '/claims/' + row['id'] + '/deactivate', headers=headers('c'),
                               json={'revision': row['revision']})
        assert response.status_code == 200, response.text
        row = response.json()['claim']
        assert client.get(path(row), params={'revision': row['revision']}, headers=headers('c')).status_code == 200
        assert client.get(path(row), params={'revision': row['revision']}, headers=headers('b')).status_code == 404

        admin = records['admin']['app_user_id']
        operations.set_mode(admin, mode='read_only', message='', version=operations.details(admin)['version'])
        try:
            assert client.get(path(row), params={'revision': row['revision']}, headers=headers('c')).status_code == 200
            for name in ('c', 'admin'):
                denied = client.post(base + '/media-claims', headers=headers(name), files=parts())
                assert denied.status_code == 403 and denied.json()['detail']['code'] == 'service_restricted'
                private(denied)
        finally:
            operations.set_mode(admin, mode='normal', message='', version=operations.details(admin)['version'])
        with connect(owner, 'accounts') as con:
            con.execute('UPDATE account_records SET disabled=1 WHERE app_user_id=%s', (records['c']['app_user_id'],))
        try:
            response = client.get(path(row), params={'revision': row['revision']}, headers=headers('c'))
            assert response.status_code == 403 and PRIVATE not in response.text
            private(response)
            assert client.post(base + '/media-claims', headers=headers('c'), files=parts()).status_code == 403
        finally:
            with connect(owner, 'accounts') as con:
                con.execute('UPDATE account_records SET disabled=0 WHERE app_user_id=%s', (records['c']['app_user_id'],))
            accounts.drain_projection()
