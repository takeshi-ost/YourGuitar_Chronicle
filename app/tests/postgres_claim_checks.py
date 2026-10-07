"""Author Claim contracts against disposable, loopback PostgreSQL databases only.

Registered in run_postgres_checks.py for a permitted developer machine or CI.
Compilation/import does not start a server. No cloud credentials, external
identity provider, media service, marketplace, browser, or live data is used.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import re
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg
from psycopg import errors, sql

from ygc.admin_bootstrap_job import grant_first_admin
from ygc.claim_revision import ClaimConflict
from ygc.cloud_claim_routes import claim_router
from ygc.cloud_claims import CloudClaims
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_owner import CloudOwner
from ygc.cloud_owner_routes import owner_router
from ygc.cloud_public_catalog import CloudPublicCatalog
from ygc.db.postgres import PostgresSettings, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ServiceRestricted
from ygc.db.postgres_ownership import PostgresOwnership
from ygc.identity_platform import VerifiedIdentity
from ygc.platform_boundaries import ActorContext

ISSUER = 'local-claim-posting-fixture'
PRIVATE = 'CLAIM-PRIVATE-DO-NOT-PUBLISH'
BIG_ID = 9007199254741009
OWN_FIELDS = {'id', 'individual_id', 'claim_type', 'specification_kind',
              'incident_kind', 'event_kind', 'field_name', 'value_text', 'body', 'occurred_at',
              'status', 'verification_status', 'created_at', 'updated_at',
              'spec_items', 'revision'}
PUBLIC_CLAIM_FIELDS = {'id', 'claim_type', 'ownership_kind', 'occurred_at',
                       'created_at', 'verification_status', 'items', 'source_url'}


def rejected(error, operation):
    try:
        operation()
    except error:
        return
    raise AssertionError('Expected ' + error.__name__)


def specification(*, kind='specification', body=PRIVATE, items=None, date='2026-03-01'):
    return dict(claim_type='specification', specification_kind=kind,
                items=items if items is not None else [
                    dict(field_name='neck', value_text='Maple'),
                    dict(field_name='pickups', value_text='Two single coils')],
                body=body, occurred_at=date)


def incident(*, kind='damage', body=PRIVATE, date='2026-03-01'):
    return dict(claim_type='incident', incident_kind=kind, body=body, occurred_at=date)


def run(port):
    prefix = 'ygctest_claims_' + uuid.uuid4().hex[:10] + '_'
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
            assert grant_first_admin(app, records['admin']['app_user_id'], 'local-test-operator')
            accounts.drain_projection()
            operations.set_mode(records['admin']['app_user_id'], mode='normal', message='',
                                version=operations.details(records['admin']['app_user_id'])['version'])
            # Sequence initialization is privileged disposable fixture setup;
            # service checks below still use the restricted runtime role.
            fixture = seed(owner, records)
            # Any accidental write through the legacy Observation table fails.
            with connect(owner, 'chronicle') as con:
                con.execute(sql.SQL('REVOKE INSERT,UPDATE,DELETE ON observations FROM {}')
                            .format(sql.Identifier(runtime)))
            checks(app, owner, accounts, operations, records, fixture)
            print('PostgreSQL author Claims: real shared inserts/multi-item edits, atomic notifications, '
                  'Owner/Acquire authority transitions, stale decisions and tombstones, private paging, '
                  'canonical account/projection fences, service modes, HTTP identity and public privacy passed.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))


def seed(settings, records):
    with connect(settings, 'chronicle') as con:
        for individual in (BIG_ID, BIG_ID + 1, BIG_ID + 2):
            con.execute('''INSERT INTO individuals(id,manufacturer,model,serial_number,
                normalized_manufacturer,normalized_model,normalized_serial,
                location_country,location_region,current_owner_user_id,created_at,updated_at)
                VALUES(%s,'Fender','Telecaster',%s,'fender','telecaster',%s,%s,%s,%s,
                       '2026-01-01','2026-01-01')''',
                (individual, 'CLAIM-' + str(individual), str(individual), PRIVATE, PRIVATE,
                 records['a']['id'] if individual != BIG_ID + 2 else None))
        # Exercise exact string identifiers above JavaScript's safe-integer range.
        con.execute("SELECT setval(pg_get_serial_sequence('claims','id'),%s,false)", (BIG_ID + 20,))
        listings = []
        for individual in (BIG_ID, BIG_ID + 1):
            listing = con.execute('''INSERT INTO claims(individual_id,author_user_id,
                claim_type,verification_status,occurred_at,created_at,updated_at)
                VALUES(%s,%s,'listing','positive','2026-01-01','2026-01-01','2026-01-01')
                RETURNING id''', (individual, records['a']['id'])).fetchone()['id']
            listings.append(listing)
            for field, value in (('manufacturer', 'Fender'), ('model', 'Telecaster'),
                    ('serial_number', 'CLAIM-' + str(individual)),
                    ('owner_user_id', str(records['a']['id']))):
                con.execute('''INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at)
                    VALUES(%s,%s,%s,'2026-01-01')''', (listing, field, value))
            con.execute('''INSERT INTO user_guitars(user_id,individual_id,ownership_status,
                created_at,updated_at) VALUES(%s,%s,'current_owner','2026-01-01','2026-01-01')''',
                (records['a']['id'], individual))
        hidden_claim = con.execute('''INSERT INTO claims(individual_id,author_user_id,
            claim_type,field_name,value_text,body,status,verification_status,
            occurred_at,created_at,updated_at)
            VALUES(%s,%s,'incident','incident_kind','lost',%s,'inactive','unverified',
                   '2026-02-01','2026-02-01','2026-02-01') RETURNING id''',
            (BIG_ID + 2, records['b']['id'], PRIVATE)).fetchone()['id']
    return dict(individual=BIG_ID, other=BIG_ID + 1, hidden=BIG_ID + 2,
                hidden_claim=hidden_claim, listing=listings[0])


def checks(settings, db_owner, accounts, operations, records, fixture):
    service, owners = CloudClaims(settings, operations), CloudOwner(settings, operations)
    catalog, ownership = CloudPublicCatalog(settings, operations), PostgresOwnership(settings)
    individual = fixture['individual']
    actors = {name: row['app_user_id'] for name, row in records.items()}

    def create(name, data):
        row = service.create(actors[name], individual, data)['claim']
        assert set(row) == OWN_FIELDS
        assert isinstance(row['id'], str) and int(row['id']) > 2**53
        assert row['individual_id'] == str(individual)
        assert re.fullmatch('[0-9a-f]{64}', row['revision'])
        with connect(settings, 'chronicle') as con:
            stored = con.execute('SELECT * FROM claims WHERE id=%s', (int(row['id']),)).fetchone()
            assert stored['author_user_id'] == records[name]['id']
            assert stored['individual_id'] == individual and stored['observation_id'] is None
            items = con.execute('SELECT field_name,value_text FROM claim_spec_items WHERE claim_id=%s ORDER BY id',
                                (int(row['id']),)).fetchall()
            assert [dict(item) for item in items] == row['spec_items']
        return row

    def own(name, claim):
        return next(row for row in service.list(actors[name], individual, limit=50)['items']
                    if row['id'] == str(claim))

    def pending(name, claim):
        return next(row for row in owners.pending(actors[name], individual)['items']
                    if row['id'] == str(claim))

    def edit(name, row, data):
        return service.edit(actors[name], individual, int(row['id']),
                            data | {'revision': row['revision']})['claim']

    def respond(name, row, stance):
        return owners.respond(actors[name], individual, int(row['id']),
                              dict(stance=stance, revision=row['revision']))

    def snapshot():
        with connect(settings, 'chronicle') as con:
            return {table: [dict(row) for row in con.execute('SELECT * FROM ' + table + ' ORDER BY id')]
                    for table in ('claims', 'claim_spec_items', 'notifications', 'individuals', 'user_guitars')}

    def mode(value):
        admin = actors['admin']
        operations.set_mode(admin, mode=value, message='', version=operations.details(admin)['version'])

    # Owner defaults, third-party review, exact content, generated IDs and notices.
    owner_spec = create('a', specification())
    assert owner_spec['verification_status'] == 'positive'
    assert owner_spec['field_name'] is None and owner_spec['value_text'] is None
    third = create('b', specification(kind='repair', body=None))
    assert third['verification_status'] == 'unverified' and third['body'] is None
    review = pending('a', third['id'])
    assert review['spec_items'] == third['spec_items'] and review['specification_kind'] == 'repair'
    assert owners.pending(actors['a'], individual)['can_write'] is True
    with connect(settings, 'chronicle') as con:
        notifications = con.execute("SELECT * FROM notifications WHERE notification_type='claim_added' ORDER BY id").fetchall()
        assert len(notifications) == 1 and notifications[0]['claim_id'] == int(third['id'])
        assert notifications[0]['recipient_user_id'] == records['a']['id']
        assert notifications[0]['actor_user_id'] == records['b']['id']
    assert owners.pending(actors['b'], individual)['items'] == []
    for stance in ('positive', 'negative', 'unverified'):
        rejected(ValueError, lambda: respond('a', owner_spec, stance))
        rejected(ValueError, lambda: respond('b', third, stance))

    # Changes invalidate both the author's editor and the Owner's open review.
    changed_data = specification(kind='repair', body=PRIVATE + '-edited', items=[
        dict(field_name='bridge', value_text='Brass bridge'),
        dict(field_name='pickups', value_text='New single coils')])
    changed = edit('b', third, changed_data)
    assert changed['verification_status'] == 'unverified' and changed['revision'] != third['revision']
    rejected(ClaimConflict, lambda: edit('b', third, changed_data))
    rejected(ClaimConflict, lambda: respond('a', review, 'positive'))
    review = pending('a', third['id'])
    respond('a', review, 'positive')
    rejected(ClaimConflict, lambda: edit('b', changed, changed_data))
    accepted = own('b', third['id'])
    assert accepted['verification_status'] == 'positive'
    accepted = edit('b', accepted, changed_data | {'body': PRIVATE + '-still-positive'})
    assert accepted['verification_status'] == 'positive'
    respond('a', pending('a', third['id']), 'negative')
    negative = own('b', third['id'])
    negative = edit('b', negative, changed_data | {'body': PRIVATE + '-still-negative'})
    assert negative['verification_status'] == 'negative'
    respond('a', pending('a', third['id']), 'unverified')
    assert edit('b', own('b', third['id']), changed_data)['verification_status'] == 'unverified'

    # A DB edit with the same Claim timestamp must still stale both tokens.
    before_content = own('b', third['id'])
    before_review = pending('a', third['id'])
    with connect(settings, 'chronicle') as con:
        con.execute("UPDATE claim_spec_items SET value_text='Same-stamp replacement' WHERE claim_id=%s AND field_name='bridge'",
                    (int(third['id']),))
    after_content = own('b', third['id'])
    assert after_content['updated_at'] == before_content['updated_at']
    assert after_content['revision'] != before_content['revision']
    rejected(ClaimConflict, lambda: edit('b', before_content, changed_data))
    rejected(ClaimConflict, lambda: respond('a', before_review, 'positive'))

    # Types and Incident subtypes remain fixed; all three incident kinds store
    # their normal Claim representation and never masquerade as Ownership Lost.
    incidents = [create('b', incident(kind=kind)) for kind in ('damage', 'lost', 'theft')]
    for row, kind in zip(incidents, ('damage', 'lost', 'theft')):
        assert row['claim_type'] == 'incident' and row['incident_kind'] == kind
        assert row['field_name'] == 'incident_kind' and row['value_text'] == kind
        assert row['spec_items'] == [] and row['verification_status'] == 'unverified'
        assert edit('b', row, incident(kind=kind, body=PRIVATE + '-details'))['incident_kind'] == kind
    current_incident = own('b', incidents[0]['id'])
    rejected(ValueError, lambda: edit('b', current_incident, incident(kind='theft')))
    rejected(ValueError, lambda: edit('b', current_incident, specification()))
    rejected(ValueError, lambda: edit('b', own('b', third['id']), incident()))

    # Private author listing excludes foreign content and unsupported Claim types.
    assert all(row['id'] != third['id'] for row in service.list(actors['a'], individual)['items'])
    assert service.list(actors['c'], individual)['items'] == []
    for name in ('a', 'c', 'admin'):
        rejected(GuitarMissing, lambda: edit(name, own('b', third['id']), changed_data))
        rejected(GuitarMissing, lambda: service.deactivate(actors[name], individual,
            int(third['id']), {'revision': own('b', third['id'])['revision']}))
    rejected(GuitarMissing, lambda: service.edit(actors['b'], fixture['other'], int(third['id']),
        changed_data | {'revision': own('b', third['id'])['revision']}))
    rejected(GuitarMissing, lambda: service.deactivate(actors['a'], individual,
        fixture['listing'], {'revision': 'a' * 64}))

    # Inactivation retains the row/content, stales all open actions, and stays
    # available in the private list while disappearing from Owner/public views.
    retiring = own('b', incidents[1]['id'])
    retirement_review = pending('a', retiring['id'])
    inactive = service.deactivate(actors['b'], individual, int(retiring['id']),
                                 {'revision': retiring['revision']})['claim']
    assert inactive['status'] == 'inactive' and inactive['body'] == retiring['body']
    assert inactive['verification_status'] == retiring['verification_status']
    assert inactive['revision'] != retiring['revision']
    assert own('b', retiring['id']) == inactive
    rejected(ClaimConflict, lambda: edit('b', retiring, incident(kind='lost')))
    rejected(ClaimConflict, lambda: edit('b', inactive, incident(kind='lost')))
    rejected(ClaimConflict, lambda: service.deactivate(actors['b'], individual,
        int(inactive['id']), {'revision': inactive['revision']}))
    rejected(ClaimConflict, lambda: respond('a', retirement_review, 'positive'))
    assert inactive['id'] not in {row['id'] for row in owners.pending(actors['a'], individual)['items']}
    full = service.list(actors['b'], individual, limit=50)['items']
    paged, after = [], 0
    while True:
        page = service.list(actors['b'], individual, after=after, limit=2)
        assert set(page) == {'individual', 'items', 'can_write', 'next_after'}
        assert set(page['individual']) == {'id', 'manufacturer', 'model', 'finish', 'year', 'serial_number'}
        paged.extend(page['items'])
        if page['next_after'] is None:
            break
        assert page['next_after'] == page['items'][-1]['id']
        after = int(page['next_after'])
        assert len(paged) <= len(full), 'Private cursor did not advance'
    assert paged == full and [int(row['id']) for row in full] == sorted({int(row['id']) for row in full}, reverse=True)

    # Shared PG item insertion and notification failures roll back the entire
    # write, including replacement item deletes and Snapshot/projection updates.
    for table, operation in (
        ('claim_spec_items', lambda: create('b', specification())),
        ('claim_spec_items', lambda: edit('b', own('b', third['id']), changed_data)),
        ('notifications', lambda: create('b', incident())),
    ):
        before = snapshot()
        with connect(db_owner, 'chronicle') as con:
            con.execute(sql.SQL('REVOKE INSERT ON {} FROM {}').format(sql.Identifier(table), sql.Identifier(settings.user)))
        try:
            rejected(errors.InsufficientPrivilege, operation)
            assert snapshot() == before
        finally:
            with connect(db_owner, 'chronicle') as con:
                con.execute(sql.SQL('GRANT INSERT ON {} TO {}').format(sql.Identifier(table), sql.Identifier(settings.user)))

    # Even a failure after the tombstone UPDATE must restore the active Claim.
    before = snapshot()
    current = own('b', third['id'])
    with connect(db_owner, 'chronicle') as con:
        con.execute(sql.SQL('REVOKE UPDATE ON individuals FROM {}').format(sql.Identifier(settings.user)))
    try:
        rejected(errors.InsufficientPrivilege, lambda: service.deactivate(actors['b'], individual,
            int(current['id']), {'revision': current['revision']}))
        assert snapshot() == before
    finally:
        with connect(db_owner, 'chronicle') as con:
            con.execute(sql.SQL('GRANT UPDATE ON individuals TO {}').format(sql.Identifier(settings.user)))

    # Overlapping stale writers may lose the maintenance try-lock or the
    # compare-and-swap check, but exactly one committed body is accepted.
    concurrent = own('b', third['id'])
    def racing_edit(value):
        try:
            return edit('b', concurrent, changed_data | {'body': value})['body']
        except ClaimConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(racing_edit, ('race-left', 'race-right')))
    assert sum(value is not None for value in outcomes) == 1
    assert own('b', third['id'])['body'] == next(value for value in outcomes if value is not None)

    # A's approval of B's dated Acquire moves both ownership and authority.
    # B's own Acquire cannot be self-decided; a new A Claim is now Unverified.
    waiting = create('c', incident())
    old_owner_review = pending('a', waiting['id'])
    with connect(settings, 'chronicle') as con:
        acquire = con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,
            ownership_kind,ownership_source,value_text,verification_status,occurred_at,created_at,updated_at)
            VALUES(%s,%s,'ownership','acquire','user',%s,'unverified','2026-04-01','2026-04-01','2026-04-01')
            RETURNING id''', (individual, records['b']['id'], str(records['b']['id']))).fetchone()['id']
        con.execute("INSERT INTO claim_source_evidence(claim_id,evidence_type,effective_date,created_at) VALUES(%s,'acquisition_date','2026-04-01','2026-04-01')", (acquire,))
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (individual,)).fetchone()['current_owner_user_id'] == records['a']['id']
        assert not con.execute('SELECT 1 FROM user_guitars WHERE individual_id=%s AND user_id=%s', (individual, records['b']['id'])).fetchone()
    respond('a', pending('a', acquire), 'positive')
    with connect(settings, 'chronicle') as con:
        assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (individual,)).fetchone()['current_owner_user_id'] == records['b']['id']
        statuses = {row['user_id']: row['ownership_status'] for row in con.execute(
            'SELECT user_id,ownership_status FROM user_guitars WHERE individual_id=%s', (individual,))}
        assert statuses[records['a']['id']] == 'former_owner' and statuses[records['b']['id']] == 'current_owner'
    rejected(ValueError, lambda: respond('a', old_owner_review, 'positive'))
    respond('b', pending('b', waiting['id']), 'positive')
    assert create('a', incident())['verification_status'] == 'unverified'
    assert create('b', specification())['verification_status'] == 'positive'
    principal = lambda name: ActorContext(records[name]['id'], 'identity-platform', name, True, actors[name])
    for stance in ('positive', 'negative', 'unverified'):
        rejected(ValueError, lambda: ownership.set_claim_response(acquire, principal('b'), stance))
    rejected(PermissionError, lambda: ownership.admin_moderate_claim(int(waiting['id']), principal('a'), 'negative'))
    # The explicit Admin path is still separate, and the current Owner can then
    # re-evaluate another user's Claim after that administrative decision.
    ownership.admin_moderate_claim(int(waiting['id']), principal('admin'), 'negative')
    moderated = own('c', waiting['id'])
    assert moderated['verification_status'] == 'negative'
    with connect(settings, 'chronicle') as con:
        flags = con.execute('SELECT verification_status,admin_verification FROM claims WHERE id=%s',
                            (int(waiting['id']),)).fetchone()
        assert flags['admin_verification'] == 1
    edited_moderated = edit('c', moderated, incident(body=PRIVATE + '-admin-decision-preserved'))
    assert edited_moderated['verification_status'] == 'negative'
    with connect(settings, 'chronicle') as con:
        assert con.execute('SELECT verification_status,admin_verification FROM claims WHERE id=%s',
                           (int(waiting['id']),)).fetchone() == flags
    respond('b', pending('b', waiting['id']), 'positive')

    # Source-account revocation and undelivered participant projection changes
    # block subsequent writes even when the content user still looks valid.
    for column, value, restore in (('disabled', 1, 0), ('ban_status', 'ban', 'normal'),
                                   ('account_type', 'source', 'user')):
        before = snapshot()
        with connect(settings, 'accounts') as con:
            con.execute(sql.SQL('UPDATE account_records SET {}=%s WHERE app_user_id=%s')
                        .format(sql.Identifier(column)), (value, actors['b']))
        rejected(PermissionError, lambda: service.create(actors['b'], individual, incident()))
        assert snapshot() == before
        with connect(settings, 'accounts') as con:
            con.execute(sql.SQL('UPDATE account_records SET {}=%s WHERE app_user_id=%s')
                        .format(sql.Identifier(column)), (restore, actors['b']))
        accounts.drain_projection()
    accounts.update_profile(actors['c'], {'bio': PRIVATE + '-pending'})
    before = snapshot()
    rejected(ValueError, lambda: service.create(actors['b'], individual, incident()))
    rejected(ValueError, lambda: service.edit(actors['b'], individual, int(third['id']),
        changed_data | {'revision': 'a' * 64}))
    assert snapshot() == before
    accounts.drain_projection()
    create('b', incident(body=PRIVATE + '-projection-delivered'))

    # Ordinary authenticated actions obey PR #52 service modes even for Admin.
    admin_claim = create('admin', incident())
    mode('read_only')
    for name in ('admin', 'a', 'b'):
        assert service.list(actors[name], individual)['can_write'] is False
        assert owners.pending(actors[name], individual)['can_write'] is False
        rejected(ServiceRestricted, lambda: service.create(actors[name], individual, incident()))
    rejected(ServiceRestricted, lambda: edit('admin', admin_claim, incident()))
    rejected(ServiceRestricted, lambda: service.deactivate(actors['admin'], individual,
        int(admin_claim['id']), {'revision': admin_claim['revision']}))
    rejected(ServiceRestricted, lambda: respond('b', pending('b', admin_claim['id']), 'positive'))
    mode('offline')
    for name in ('admin', 'a', 'b'):
        rejected(ServiceRestricted, lambda: service.list(actors[name], individual))
        rejected(ServiceRestricted, lambda: service.create(actors[name], individual, incident()))
        rejected(ServiceRestricted, lambda: owners.pending(actors[name], individual))
    mode('admin_only')
    for name in ('a', 'b'):
        rejected(ServiceRestricted, lambda: service.list(actors[name], individual))
        rejected(ServiceRestricted, lambda: service.create(actors[name], individual, incident()))
    assert service.list(actors['admin'], individual)['can_write'] is True
    admin_claim = edit('admin', admin_claim, incident(body=PRIVATE + '-admin-only'))
    assert create('admin', specification())['verification_status'] == 'unverified'
    # An already-resolved browser identity does not retain a revoked Admin role.
    with connect(settings, 'accounts') as con:
        con.execute("UPDATE account_records SET role='member' WHERE app_user_id=%s", (actors['admin'],))
    rejected(ServiceRestricted, lambda: service.create(actors['admin'], individual, incident()))
    with connect(settings, 'accounts') as con:
        con.execute("UPDATE account_records SET role='admin' WHERE app_user_id=%s", (actors['admin'],))
    accounts.drain_projection()
    mode('normal')

    # A held maintenance/crawl mutex rejects writes, without preventing reads.
    before = snapshot()
    with connect(settings, 'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        assert service.list(actors['b'], individual)['can_write'] is True
        rejected(ClaimConflict, lambda: service.create(actors['b'], individual, incident()))
        rejected(ClaimConflict, lambda: edit('admin', admin_claim, incident()))
        rejected(ClaimConflict, lambda: service.deactivate(actors['admin'], individual,
            int(admin_claim['id']), {'revision': admin_claim['revision']}))
    assert snapshot() == before

    # Public projection remains the existing allowlist. Body, custom spec data,
    # author/location identity and Incident detail never become public fields.
    private_spec = create('b', specification(items=[dict(field_name='owner_private_note', value_text=PRIVATE)]))
    public = catalog.chronicle(None, individual, limit=50)
    assert PRIVATE not in json.dumps(public) and PRIVATE not in json.dumps(catalog.detail(None, individual))
    for row in public['items']:
        assert set(row) == PUBLIC_CLAIM_FIELDS
    by_id = {row['id']: row for row in public['items']}
    assert by_id[private_spec['id']]['items'] == []
    assert inactive['id'] not in by_id
    assert all(row['id'] != str(fixture['listing']) for row in service.list(actors['a'], individual)['items'])
    with connect(settings, 'chronicle') as con:
        assert con.execute('SELECT COUNT(*) AS n FROM observations').fetchone()['n'] == 0

    # Private GETs, like the public projection, do not perform repairs, promote
    # media, refresh snapshots, or write any application/projection state.
    readonly_tables = ('claims', 'claim_spec_items', 'notifications', 'individuals', 'user_guitars')
    before = snapshot()
    with connect(db_owner, 'chronicle') as con:
        for table in readonly_tables:
            con.execute(sql.SQL('REVOKE INSERT,UPDATE,DELETE ON {} FROM {}').format(
                sql.Identifier(table), sql.Identifier(settings.user)))
    try:
        assert service.list(actors['b'], individual)['items']
        assert owners.pending(actors['b'], individual)['items']
        assert catalog.chronicle(None, individual)['items']
        assert snapshot() == before
    finally:
        with connect(db_owner, 'chronicle') as con:
            for table in readonly_tables:
                con.execute(sql.SQL('GRANT INSERT,UPDATE,DELETE ON {} TO {}').format(
                    sql.Identifier(table), sql.Identifier(settings.user)))

    http_checks(settings, accounts, operations, service, owners, records, fixture)


def http_checks(settings, accounts, operations, service, owners, records, fixture):
    class Verifier:
        def __init__(self):
            self.accounts = accounts

        def verify(self, *, bearer_token):
            if bearer_token == 'unavailable':
                raise RuntimeError(PRIVATE)
            if bearer_token not in (*records, 'unverified'):
                raise PermissionError(PRIVATE)
            return VerifiedIdentity(ISSUER, 'b' if bearer_token == 'unverified' else bearer_token,
                                    '', bearer_token != 'unverified')

    api = FastAPI()
    api.include_router(claim_router(Verifier(), service))
    api.include_router(owner_router(Verifier(), owners))
    base = f"/api/auth/guitars/{fixture['individual']}/claims"
    headers = lambda name: {'Authorization': 'Bearer ' + name}
    with TestClient(api) as client:
        for name, code in (('invalid', 401), ('unverified', 403), ('unavailable', 503)):
            response = client.get(base, headers=headers(name))
            assert response.status_code == code and PRIVATE not in response.text
        assert client.get(base).status_code == 401
        response = client.get(base, headers=headers('b'), params={'limit': 2})
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Authorization'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert len(response.json()['items']) == 2
        for query in ('user_id=1', 'author_user_id=1', 'role=admin', 'after=0',
                      'limit=0', 'limit=51', 'limit=1&limit=2'):
            assert client.get(base + '?' + query, headers=headers('b')).status_code == 400
        for identifier, code in (('0', 400), ('-1', 400), ('1.0', 400),
                                 (str(2**63), 400), ('1234567', 404), (str(fixture['hidden']), 404)):
            path = f'/api/auth/guitars/{identifier}/claims'
            assert client.get(path, headers=headers('a')).status_code == code
            assert client.post(path, headers=headers('a'), json=incident()).status_code == code
        hidden = client.get(f"/api/auth/guitars/{fixture['hidden']}/claims", headers=headers('b'))
        assert hidden.status_code == 200, hidden.text
        assert hidden.json()['items'][0]['id'] == str(fixture['hidden_claim'])
        assert hidden.json()['items'][0]['status'] == 'inactive'

        response = client.post(base, headers=headers('b'), json=incident(body=PRIVATE + '-http'))
        assert response.status_code == 200, response.text
        row = response.json()['claim']
        path = base + '/' + row['id']
        # Foreign authors and even a legitimate Admin see the same missing shape.
        for name in ('a', 'c', 'admin'):
            denied = client.patch(path, headers=headers(name), json=incident() | {'revision': row['revision']})
            assert denied.status_code == 404 and PRIVATE not in denied.text
            assert client.post(path + '/deactivate', headers=headers(name),
                               json={'revision': row['revision']}).status_code == 404
        edited = client.patch(path, headers=headers('b'), json=incident(body=PRIVATE + '-http-edit') | {'revision': row['revision']})
        assert edited.status_code == 200, edited.text
        assert client.patch(path, headers=headers('b'), json=incident() | {'revision': row['revision']}).status_code == 409
        row = edited.json()['claim']
        dead = client.post(path + '/deactivate', headers=headers('b'), json={'revision': row['revision']})
        assert dead.status_code == 200 and dead.json()['claim']['status'] == 'inactive'
        assert client.post(path + '/deactivate', headers=headers('b'), json={'revision': row['revision']}).status_code == 409
        assert client.post(base, headers=headers('b'), json=incident() | {'author_user_id': records['a']['id']}).status_code == 400
        assert client.post(base, headers=headers('b') | {'Origin': 'https://untrusted.invalid'}, json=incident()).status_code == 403
        assert client.post(base, headers=headers('b') | {'X-YGC-Timezone': 'Invalid/Zone'}, json=incident()).status_code == 400
        assert client.post(base, headers=headers('b'), json=incident(date='9999-01-01')).status_code == 400

        # Verify the complete HTTP path reads current service mode and source
        # authority each time, with no Admin bypass for ordinary writes.
        admin = records['admin']['app_user_id']
        operations.set_mode(admin, mode='read_only', message='', version=operations.details(admin)['version'])
        for name in ('b', 'admin'):
            assert client.get(base, headers=headers(name)).json()['can_write'] is False
            owner_path = f"/api/auth/guitars/{fixture['individual']}/owner-responses"
            assert client.get(owner_path, headers=headers(name)).json()['can_write'] is False
            denied = client.post(base, headers=headers(name), json=incident())
            assert denied.status_code == 403 and denied.json()['detail']['code'] == 'service_restricted'
        operations.set_mode(admin, mode='normal', message='', version=operations.details(admin)['version'])
        with connect(settings, 'accounts') as con:
            con.execute('UPDATE account_records SET disabled=1 WHERE app_user_id=%s', (records['b']['app_user_id'],))
        for method in ('get', 'post'):
            response = getattr(client, method)(base, headers=headers('b'), **({'json': incident()} if method == 'post' else {}))
            assert response.status_code == 403 and PRIVATE not in response.text
        with connect(settings, 'accounts') as con:
            con.execute('UPDATE account_records SET disabled=0 WHERE app_user_id=%s', (records['b']['app_user_id'],))
        accounts.drain_projection()
