"""Public catalog contracts on disposable local PostgreSQL databases only.

Invoked by run_postgres_checks.py on a permitted developer machine or CI.
Preparing or compiling this file does not execute PostgreSQL. The source URL
fixtures exercise an allowlist, not permission to retrieve a marketplace.
No live data, real authentication, external photo, or cloud service is used.
"""
from dataclasses import replace
import json
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg
from psycopg import sql

from ygc.admin_bootstrap_job import grant_first_admin
from ygc.cloud_public_catalog import CloudPublicCatalog
from ygc.cloud_public_catalog_routes import public_catalog_router
from ygc.db.postgres import PostgresSettings, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations
from ygc.identity_platform import VerifiedIdentity

BASE = '/api/public/guitars'
BIG_ID = 9007199254741009
PRIVATE = 'CATALOG-PRIVATE-DO-NOT-PUBLISH'
CARD_FIELDS = {'id', 'manufacturer', 'model', 'finish', 'year', 'serial_number', 'photo', 'claim_count'}
CLAIM_FIELDS = {'id', 'claim_type', 'ownership_kind', 'occurred_at', 'created_at',
                'verification_status', 'items', 'source_url', 'presentation'}


def rejected(error, action):
    try:
        action()
    except error:
        return
    raise AssertionError('Expected ' + error.__name__)


def run(port):
    prefix = 'ygctest_public_catalog_' + uuid.uuid4().hex[:10] + '_'
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
            records = {name: accounts.ensure_identity(issuer='public-catalog-fixture',
                subject=name, display_name='Public member-' + name)
                for name in ('admin', 'member', 'banned', 'silent', 'disabled')}
            admin = records['admin']['app_user_id']
            assert grant_first_admin(app, admin, 'local-test-operator')
            with connect(app, 'accounts') as con:
                for name, state in (('banned', 'ban'), ('silent', 'silent_ban')):
                    con.execute('UPDATE account_records SET ban_status=%s WHERE app_user_id=%s',
                                (state, records[name]['app_user_id']))
                con.execute('UPDATE account_records SET disabled=1 WHERE app_user_id=%s',
                            (records['disabled']['app_user_id'],))
            accounts.drain_projection()
            operations.set_mode(admin, mode='normal', message='',
                                version=operations.details(admin)['version'])
            fixture = seed(app, records)
            checks(app, owner, accounts, operations, records, fixture)
            print('PostgreSQL public catalog: strict anonymous/verified identity and service modes, '
                  'active Claim privacy, fixed public fields, canonical source allowlist, '
                  'read-only reads, escaped search and deterministic pagination passed.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))


def seed(settings, records):
    claims = {}
    with connect(settings, 'chronicle') as con:
        def guitar(identifier, maker, model, *, created='2026-01-01'):
            con.execute('''INSERT INTO individuals(id,manufacturer,model,finish,year,
                serial_number,normalized_manufacturer,normalized_model,normalized_serial,
                location_country,location_region,current_owner_name,current_owner_type,
                current_owner_user_id,current_owner_source_url,created_at,updated_at)
                VALUES(%s,%s,%s,'Sunburst','1960',%s,%s,%s,%s,%s,%s,%s,'user',%s,%s,%s,%s)''',
                (identifier, maker, model, 'SERIAL-' + str(identifier), maker.lower(),
                 model.lower(), str(identifier), PRIVATE, PRIVATE, PRIVATE,
                 records['member']['id'], 'https://private.invalid/' + PRIVATE, created, created))

        def claim(guitar_id, *, kind='listing', status='active', verification='positive',
                  author='member', occurred='2026-01-01', ownership=None,
                  field='private-field', value=PRIVATE, created=None):
            created = created or occurred or '2026-01-01'
            row = con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,
                ownership_kind,status,verification_status,field_name,value_text,body,
                previous_owner_text,occurred_at,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                (guitar_id, records[author]['id'], kind, ownership, status, verification,
                 field, value, 'Public Claim prose', PRIVATE, occurred, created, created)).fetchone()
            return row['id']

        def items(table, claim_id, values):
            for field, value in values.items():
                con.execute(sql.SQL('INSERT INTO {}(claim_id,field_name,value_text,created_at) '
                                    "VALUES(%s,%s,%s,'2026-01-01')").format(sql.Identifier(table)),
                            (claim_id, field, value))

        def source(claim_id, url, *, site='reverb', listing=None, evidence='marketplace_listing'):
            if listing is None:
                listing = str(20000 + claim_id)
                url = url.replace('/item/12345', '/item/' + listing)
            con.execute('''INSERT INTO claim_source_evidence(claim_id,evidence_type,
                source_site,source_listing_id,source_url,payload_json,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,'2026-01-01')''',
                (claim_id, evidence, site, listing, url, json.dumps({'private': PRIVATE})))

        fixtures = ((10, 'Fender', 'Alpha'), (11, 'Fender', 'Alpha'),
                    (12, 'Gibson', 'Beta'), (13, r'100%_\\ maker', 'Literal'),
                    (14, 'Ibanez', 'Negative only'), (15, 'Yamaha', 'Unverified only'),
                    (BIG_ID, 'Zemaitis', 'Big identifier'))
        for identifier, maker, model in fixtures:
            guitar(identifier, maker, model, created='2026-02-01' if identifier >= 14 else '2026-01-01')
            verification = {14: 'negative', 15: 'unverified'}.get(identifier, 'positive')
            claims[identifier] = claim(identifier, verification=verification)
        visible = [row[0] for row in fixtures]
        hidden = []
        for identifier, options in ((100, {'status': 'inactive'}),
                (101, {'author': 'banned'}), (102, {'author': 'silent'}),
                (104, {'kind': 'future-private-kind'}),
                (105, {'verification': 'future-private-status'})):
            guitar(identifier, 'Hidden', 'Hidden ' + str(identifier))
            claim(identifier, **options)
            hidden.append(identifier)
        guitar(103, 'Hidden', 'No claims')
        hidden.append(103)
        # With a permitted Claim present, excluded neighbors must still stay out.
        excluded = [claim(10, status='inactive'), claim(10, author='banned'),
                    claim(10, author='silent'), claim(10, kind='future-private-kind'),
                    claim(10, verification='future-private-status')]
        positive = claims[10]
        items('claim_listing_items', positive, dict(manufacturer='Fender', model='Alpha',
            finish='Sunburst', serial_number='SERIAL-10', year='1960',
            owner_name=PRIVATE, location_country=PRIVATE, source_url=PRIVATE,
            listing_title=PRIVATE))
        source(positive, 'https://www.reverb.com/item/12345-fixture-guitar/', listing='12345')
        specs = claim(10, kind='specification', occurred='2026-03-01')
        items('claim_spec_items', specs, dict(neck='Maple',
            pickups='SSS', bridge='Earlier bridge', owner_name=PRIVATE, arbitrary_note=PRIVATE))
        con.execute('UPDATE claims SET field_name=%s,value_text=%s WHERE id=%s',
                    ('neck', 'Legacy neck loses to structured neck', specs))
        legacy_specs = claim(10, kind='specification', field='bridge',
            value='Legacy brass bridge', occurred=None, created='2026-06-01')
        legacy_hidden = [claim(10, kind='specification', field=field, value=value,
            occurred=None, created='2026-07-01') for field, value in (
                (None, PRIVATE), ('owner_name', PRIVATE), ('bridge', None))]
        older_specs = claim(10, kind='specification', occurred='2025-01-01')
        items('claim_spec_items', older_specs, dict(neck='Earlier neck'))
        for options in ({'status': 'inactive'}, {'author': 'banned'}, {'author': 'silent'}):
            identifier = claim(10, kind='specification', occurred='2026-04-01', **options)
            items('claim_spec_items', identifier, dict(neck=PRIVATE))
            excluded.append(identifier)
        nonpositive = []
        for verification in ('negative', 'unverified'):
            identifier = claim(10, kind='specification', verification=verification)
            items('claim_spec_items', identifier, dict(neck=PRIVATE))
            source(identifier, 'https://reverb.com/item/12345')
            nonpositive.append(identifier)
        unsafe = []
        for url, options in (
            ('javascript:alert(1)', {}), ('https://reverb.com/item/12345?token=private', {}),
            ('https://reverb.com/item/12345#private', {}), ('http://reverb.com/item/12345', {}), ('https://reverb.com.evil.invalid/item/12345', {}),
            ('https://private.invalid/item/12345', {}), ('https://reverb.com@private.invalid/item/12345', {}),
            ('https://user:password@reverb.com/item/12345', {}), ('https://reverb.com/item/%31%32%33', {}),
            ('https://reverb.com/item/12345', {'site': 'private-marketplace'}),
            ('https://reverb.com/item/12345', {'evidence': 'acquisition_date'}),
            ('https://reverb.com/item/12345', {'listing': '777'}),
        ):
            identifier = claim(10)
            source(identifier, url, **options)
            unsafe.append(identifier)
        media = con.execute('''INSERT INTO media_assets(individual_id,uploader_user_id,
            storage_path,original_filename,caption,created_at,updated_at)
            VALUES(10,%s,%s,%s,%s,'2026-01-01','2026-01-01') RETURNING id''',
            (records['member']['id'], 'gcs-content-v1:' + PRIVATE, PRIVATE, PRIVATE)).fetchone()['id']
        con.execute('UPDATE individuals SET representative_media_asset_id=%s WHERE id=10', (media,))
        con.execute("INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(%s,%s,'2026-01-01')",
                    (positive, media))
        for record in records.values():
            con.execute('UPDATE users SET bio=%s,location_country=%s,avatar_storage_path=%s WHERE id=%s',
                        (PRIVATE, PRIVATE, PRIVATE, record['id']))
    return dict(visible=visible, hidden=hidden, excluded=excluded, positive=positive,
                specs=specs, legacy_specs=legacy_specs, legacy_hidden=legacy_hidden,
                nonpositive=nonpositive, unsafe=unsafe)


def checks(settings, owner, accounts, operations, records, fixture):
    service = CloudPublicCatalog(settings, operations)
    admin = records['admin']['app_user_id']

    class Verifier:
        def __init__(self):
            self.accounts = accounts
            self.calls = []

        def verify(self, *, bearer_token):
            self.calls.append(bearer_token)
            if bearer_token == 'unavailable':
                raise RuntimeError(PRIVATE)
            if bearer_token not in (*records, 'unverified', 'unverified-admin', 'unregistered'):
                raise PermissionError(PRIVATE)
            return VerifiedIdentity('public-catalog-fixture',
                {'unverified': 'member', 'unverified-admin': 'admin'}.get(bearer_token, bearer_token),
                '', bearer_token not in ('unverified', 'unverified-admin'))

    verifier, api = Verifier(), FastAPI()
    api.include_router(public_catalog_router(verifier, service))

    def private_free(payload):
        text = json.dumps(payload)
        assert PRIVATE not in text
        for forbidden in ('gcs-content-v1:', 'storage_path', 'bucket',
                          'author_name', 'author_user_id', 'location_country', 'location_region',
                          'current_owner', 'payload_json', 'previous_owner_text'):
            assert forbidden not in text, forbidden

    def card(row, *, detail=False):
        assert set(row) == CARD_FIELDS | ({'specifications', 'presentation', 'public_photo'} if detail else set())
        assert isinstance(row['id'], str) and row['id'].isdecimal()
        assert isinstance(row['claim_count'], str) and row['claim_count'].isdecimal()
        assert int(row['claim_count']) > 0
        if row['id'] != '10':
            assert row['claim_count'] == '1'
        assert row['photo'] is None
        private_free(row)

    # DML cannot accidentally be performed by a public GET, including derived
    # expiry, projection, media promotion, or repair side effects.
    with connect(owner, 'chronicle') as con:
        con.execute(sql.SQL('REVOKE INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public FROM {}')
                    .format(sql.Identifier(settings.user)))
    with TestClient(api) as client:
        response = client.get(BASE)
        assert response.status_code == 200, response.text
        assert verifier.calls == []  # Anonymous reads never invoke an identity provider.
        assert response.headers['cache-control']=='private, no-cache, max-age=0, must-revalidate'
        assert client.get(BASE,headers={'If-None-Match':response.headers['etag']}).status_code==304
        result = response.json()
        assert set(result) == {'items', 'total', 'page', 'page_size', 'total_pages'}
        assert result['total'] == str(len(fixture['visible']))
        assert {int(row['id']) for row in result['items']} == set(fixture['visible'])
        for row in result['items']:
            card(row)
        for identifier in fixture['hidden']:
            for suffix in ('', '/chronicle'):
                assert client.get(f'{BASE}/{identifier}{suffix}').status_code == 404
        for identifier in fixture['visible']:
            detail = client.get(f'{BASE}/{identifier}')
            assert detail.status_code == 200, detail.text
            card(detail.json(), detail=True)
        detail = client.get(BASE + '/10').json()
        specs = {row['field_name']: row['value_text'] for row in detail['specifications']}
        assert specs['neck'] == 'Maple' and specs['pickups'] == 'SSS'
        assert specs['bridge'] == 'Legacy brass bridge'
        assert 'owner_name' not in specs and 'arbitrary_note' not in specs
        assert client.get(f'{BASE}/{BIG_ID}').json()['id'] == str(BIG_ID)

        # Concatenated pages are stable and exhaustive, including equal Maker,
        # Model and creation timestamp ties; repeating any page returns it intact.
        for sort in ('newest', 'oldest', 'maker', 'model', *(field+'_'+direction for field in ('manufacturer','model','finish','year','serial_number') for direction in ('asc','desc'))):
            full = client.get(BASE, params={'sort': sort}).json()['items']
            paged = []
            for number in range(1, 5):
                query = dict(sort=sort, page=number, limit=2)
                payload = client.get(BASE, params=query).json()
                assert payload == client.get(BASE, params=query).json()
                assert payload['total'] == '7' and payload['total_pages'] == 4
                assert payload['page'] == number and payload['page_size'] == 2
                paged.extend(payload['items'])
            assert paged == full and len({row['id'] for row in paged}) == 7
        for field in ('manufacturer','model','finish','year','serial_number'):
            for direction in ('asc','desc'):
                rows=client.get(BASE, params={'sort':field+'_'+direction}).json()['items']
                expected=sorted(sorted(rows,key=lambda row:int(row['id'])),key=lambda row:(row[field] or '').lower(),reverse=direction=='desc')
                assert rows==expected
        newest = client.get(BASE, params={'sort': 'newest'}).json()['items']
        oldest = client.get(BASE, params={'sort': 'oldest'}).json()['items']
        assert [row['id'] for row in newest] == [row['id'] for row in reversed(oldest)]
        assert [row['id'] for row in client.get(BASE, params={'sort': 'maker'}).json()['items'][:3]] == ['13', '10', '11']
        for query, expected in (('fEnDeR', {10, 11}), ('Alpha', {10, 11}),
                ('SERIAL-12', {12}), ('Sunburst 1960', set(fixture['visible'])), ('Fender Alpha', {10,11}), ('%', {13}), ('_', {13}), ('\\', {13}),
                ("' OR 1=1 --", set()), ('nothing-matches', set())):
            payload = client.get(BASE, params={'q': query}).json()
            assert {int(row['id']) for row in payload['items']} == expected
            assert payload['total'] == str(len(expected))

        history, after = [], None
        while True:
            query = {'limit': 2}
            if after is not None:
                query['after'] = after
            response = client.get(BASE + '/10/chronicle', params=query)
            assert response.status_code == 200, response.text
            page = response.json()
            assert set(page) == {'items', 'next_after'}
            private_free(page)
            history.extend(page['items'])
            after = page['next_after']
            if after is None:
                break
            assert isinstance(after, str) and after == page['items'][-1]['id']
            assert len(history) < 100, 'Cursor failed to advance'
        identifiers = [int(row['id']) for row in history]
        assert identifiers == sorted(set(identifiers), reverse=True)
        assert not set(identifiers) & set(fixture['excluded'])
        assert detail['claim_count'] == str(len(history)), 'Claim count includes hidden neighbors or omits visible history'
        by_id = {int(row['id']): row for row in history}
        for row in history:
            assert set(row) == CLAIM_FIELDS
            assert all(set(item) == {'field_name', 'value_text'} for item in row['items'])
        assert by_id[fixture['positive']]['source_url'] == 'https://reverb.com/item/12345'
        assert by_id[fixture['legacy_specs']]['items'] == [
            {'field_name': 'bridge', 'value_text': 'Legacy brass bridge'}]
        assert next(item for item in by_id[fixture['specs']]['items']
                    if item['field_name'] == 'neck')['value_text'] == 'Maple'
        for identifier in fixture['legacy_hidden']:
            assert by_id[identifier]['items'] == []
        for identifier in fixture['nonpositive']:
            assert by_id[identifier]['items'] == [] and by_id[identifier]['source_url'] is None
        for identifier in fixture['unsafe']:
            assert by_id[identifier]['source_url'] is None

        for query in ('viewer_id=1', 'role=admin', 'sort=unknown', 'page=0', 'page=-1',
                'limit=0', 'limit=51', 'page=1&page=2', 'q=a&q=b', 'q=%00',
                'q=' + 'x' * 121, 'sort=maker&sort=model'):
            assert client.get(BASE + '?' + query).status_code == 400, query
        for path in ('/0', '/-1', '/1.0', '/' + str(2**63), '/10?viewer_id=1',
                '/10/chronicle?after=0', '/10/chronicle?after=1&after=2',
                '/10/chronicle?q=private', '/10/chronicle?limit=51'):
            assert client.get(BASE + path).status_code == 400, path
        for suffix in ('', '/10', '/10/chronicle'):
            for method in ('post', 'put', 'patch', 'delete'):
                assert getattr(client, method)(BASE + suffix).status_code == 405
        for token, expected in (('bad-token', 401), ('unavailable', 503), ('unverified', 200), ('unverified-admin', 403),
                ('unregistered', 403), ('banned', 403), ('disabled', 403)):
            response = client.get(BASE, headers={'Authorization': 'Bearer ' + token})
            assert response.status_code == expected, (token, response.status_code, response.text)
            assert PRIVATE not in response.text
        # New Discovery/Statistics/Map share the same public-only boundary.
        discoveries = client.get(BASE + '/discoveries')
        assert discoveries.status_code == 200, discoveries.text
        news = discoveries.json()['items']
        assert {int(row['id']) for row in news} == set(fixture['visible'])
        assert len(news) == len(fixture['visible'])
        for row in news:
            assert set(row) == CARD_FIELDS | {'activity_at', 'activity_type', 'claim_type'}
            private_free(row)
        statistics = client.get(BASE + '/statistics')
        assert statistics.status_code == 200, statistics.text
        statistics = statistics.json()
        assert statistics['individuals'] == str(len(fixture['visible']))
        assert sum(int(row['count']) for row in statistics['models']) == len(fixture['visible'])
        assert statistics['years'] == [{'label': '1960', 'count': str(len(fixture['visible']))}]
        assert len(statistics['listings_30d']) == 30
        private_free(statistics)
        # All visible snapshots contain PRIVATE country. Canonical Accounts
        # default Private must suppress that stale residence for every caller.
        for token in (None, 'member', 'admin'):
            headers = {'Authorization': 'Bearer ' + token} if token else {}
            response = client.get(BASE + '/world-map', headers=headers)
            assert response.status_code == 200, response.text
            assert response.json() == {'countries': []}
        with connect(owner, 'accounts') as con:
            con.execute("UPDATE account_records SET location_country='Japan',residence_visibility='Public' WHERE id=%s",
                (records['member']['id'],))
        assert client.get(BASE + '/world-map').json() == {'countries': [{'country': 'Japan', 'count': str(len(fixture['visible']))}]}
        for visibility in ('Members', 'Followers', 'Private'):
            with connect(owner, 'accounts') as con:
                con.execute('UPDATE account_records SET residence_visibility=%s WHERE id=%s',
                    (visibility, records['member']['id']))
            assert client.get(BASE + '/world-map', headers={'Authorization': 'Bearer admin'}).json() == {'countries': []}
        for suffix in ('/discoveries', '/statistics', '/world-map'):
            assert client.get(BASE + suffix + '?viewer_id=1').status_code == 400
            for method in ('post', 'put', 'patch', 'delete'):
                assert getattr(client, method)(BASE + suffix).status_code == 405
        for mode in ('normal', 'read_only', 'admin_only', 'offline'):
            operations.set_mode(admin, mode=mode, message='', version=operations.details(admin)['version'])
            for actor in (None, 'member', 'admin'):
                headers = {'Authorization': 'Bearer ' + actor} if actor else {}
                allowed = mode in ('normal', 'read_only') or (mode == 'admin_only' and actor == 'admin')
                for suffix in ('', '/10', '/10/chronicle', '/discoveries', '/statistics', '/world-map'):
                    response = client.get(BASE + suffix, headers=headers)
                    assert (response.status_code == 200) == allowed, (mode, actor, suffix, response.text)
                    if not allowed:
                        assert response.status_code == 403
                        assert PRIVATE not in response.text
                    conditional = client.get(BASE + suffix, headers={**headers, 'If-None-Match': response.headers.get('etag', '"previously-visible"')})
                    assert conditional.status_code == (304 if allowed else 403), (mode, actor, suffix)
                    assert conditional.content == b'' if allowed else 'no-store' in conditional.headers['cache-control']
        # Supplying an arbitrary app_user_id cannot grant administrator visibility.
        rejected(PermissionError, lambda: service.list('not-a-canonical-account'))
