from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import QueryParams

from ygc.cloud_public_catalog import (CloudPublicCatalog, GUITAR_FIELDS, SPEC_FIELDS, CLAIM_TYPES,
    STATES, parameters, public_source_url, guitar_projection, claim_projection)
from ygc.cloud_public_catalog_routes import public_catalog_router
from ygc.cloud_guitars import GuitarMissing
from ygc.db.postgres_operations import ServiceRestricted
from ygc.identity_platform import VerifiedIdentity


@pytest.mark.parametrize('query', ['page=0', 'page=1000001', 'limit=51', 'limit=-1',
    'limit=1.2', 'page=١', 'sort=id;DROP TABLE claims', 'sort=newest&sort=maker',
    'q=a&q=b', 'q=%00', 'q=%0A', 'q=%7f', 'q='+'x'*121, 'viewer_id=1',
    'include=photos', 'owner=1', 'after=2', 'q=x&user_id=1'])
def test_invalid_parameters(query):
    with pytest.raises(ValueError):
        parameters(QueryParams(query))


def test_search_defaults_unicode_and_escaped_input():
    assert parameters(QueryParams()) == ('', 'newest', 1, 24)
    assert parameters(QueryParams('q=%20Fender%20%26%20%E6%9D%B1%E4%BA%AC%25_\\%20&sort=maker&page=2&limit=50')) == ('Fender & 東京%_\\', 'maker', 2, 50)


@pytest.mark.parametrize('url', ['https://reverb.com/item/42', 'https://www.reverb.com/item/42-a-guitar', 'https://reverb.com/item/42-good/'])
def test_canonical_public_source(url):
    assert public_source_url('reverb', '42', url) == 'https://reverb.com/item/42'


@pytest.mark.parametrize('url', ['http://reverb.com/item/42', 'javascript:alert(1)',
    'https://reverb.com/item/43', 'https://reverb.com/item/42?token=secret',
    'https://reverb.com/item/42#private', 'https://user:secret@reverb.com/item/42',
    'https://reverb.com.evil.test/item/42', 'https://storage.googleapis.com/private/photos',
    'gs://private/object', '/api/auth/applications/secret/photos/overview',
    'https://reverb.com:443/item/42', 'https://reverb.com/item/42\n',
    'https://reverb.com/item/42/%2e%2e', 'https://reverb.com/item/42-%', None, 42])
def test_source_url_does_not_expose_private_or_untrusted_destination(url):
    assert public_source_url('reverb', '42', url) is None


@pytest.mark.parametrize('site,listing', [('private', '42'), ('reverb', '0'), ('reverb', '42?secret'), ('reverb', None), ('reverb', '1'*21)])
def test_source_requires_exact_public_marketplace_identity(site, listing):
    assert public_source_url(site, listing, 'https://reverb.com/item/42') is None


def test_projection_allows_no_account_application_media_location_or_owner_fields():
    row = dict(id=2**63-1, manufacturer='Maker', model='Model', finish='Natural', year='1960', serial_number='42',
               current_owner_name='PRIVATE OWNER', location_region='PRIVATE HOME', author_name='PRIVATE AUTHOR',
               storage_path='gs://private/object', photo='/api/admin/media/1', application={'challenge':'PRIVATE'})
    result = guitar_projection(row)
    assert set(result) == {'id', *GUITAR_FIELDS, 'photo'}
    assert result['id'] == str(2**63-1) and result['photo'] is None
    assert 'PRIVATE' not in str(result) and 'gs://' not in str(result)


@pytest.mark.parametrize('state', STATES)
def test_chronicle_state_projection_never_exposes_free_prose_or_private_items(state):
    row = dict(id=2**63-1, claim_type='listing', ownership_kind='acquire', occurred_at='2020-01-01',
        created_at='2020-01-02', verification_status=state, body='PRIVATE BODY', value_text='PRIVATE OWNER ID',
        author_user_id=44, author_name='PRIVATE AUTHOR', revision='PRIVATE REVISION',
        evidence={'private':'PRIVATE'}, items=[dict(field_name='model', value_text='Strat'),
            dict(field_name='owner_name', value_text='PRIVATE OWNER'), dict(field_name='location_country', value_text='PRIVATE HOME'),
            dict(field_name='storage_path', value_text='gs://private/photo')], source_url='https://reverb.com/item/42')
    result = claim_projection(row)
    assert set(result) == {'id', 'claim_type', 'ownership_kind', 'occurred_at', 'created_at', 'verification_status', 'items', 'source_url'}
    assert result['items'] == ([{'field_name':'model', 'value_text':'Strat'}] if state == 'positive' else [])
    assert result['source_url'] == ('https://reverb.com/item/42' if state == 'positive' else None)
    assert 'PRIVATE' not in str(result) and 'gs://' not in str(result)


@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id':'canonical', 'role':'member'}
    service = Mock()
    service.list.return_value = dict(items=[], total=0, page=1, page_size=24, total_pages=0)
    service.detail.return_value = dict(id=1, manufacturer='Maker', specifications=[])
    service.chronicle.return_value = dict(items=[], next_after=None)
    app = FastAPI()
    app.include_router(public_catalog_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


def test_guest_does_not_need_identity_and_member_uses_canonical_identity(api):
    client, verifier, service = api
    response = client.get('/api/public/guitars?q=hello&sort=model&page=2&limit=10')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-cache, max-age=0, must-revalidate'
    assert response.headers['vary'] == 'Authorization'
    service.list.assert_called_once_with(None, q='hello', sort='model', page=2, limit=10)
    verifier.verify.assert_not_called()
    response = client.get('/api/public/guitars/1', headers={'Authorization':'Bearer valid'})
    assert response.status_code == 200
    service.detail.assert_called_once_with('canonical', 1)


@pytest.mark.parametrize('case,status', [('empty',401), ('bad_scheme',401), ('bad_token',401),
    ('identity_error',503), ('disabled',403), ('account_error',503), ('unverified_admin',403)])
def test_presented_invalid_credentials_never_downgrade_to_guest(api, case, status):
    client, verifier, service = api
    header = 'Bearer valid'
    if case == 'empty': header = ''
    if case == 'bad_scheme': header = 'Basic secret'
    if case == 'bad_token': verifier.verify.side_effect = PermissionError('PRIVATE TOKEN')
    if case == 'identity_error': verifier.verify.side_effect = RuntimeError('PRIVATE TOKEN')
    if case == 'disabled': verifier.accounts.resolve_identity.side_effect = PermissionError('PRIVATE ACCOUNT')
    if case == 'account_error': verifier.accounts.resolve_identity.side_effect = RuntimeError('PRIVATE ACCOUNT')
    if case == 'unverified_admin':
        verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
        verifier.accounts.resolve_identity.return_value['role'] = 'admin'
    response = client.get('/api/public/guitars', headers={'Authorization':header})
    assert response.status_code == status and 'PRIVATE' not in response.text
    service.list.assert_not_called()


def test_unverified_member_can_browse_same_public_fields(api):
    client, verifier, service = api
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    assert client.get('/api/public/guitars/1', headers={'Authorization':'Bearer valid'}).status_code == 200


@pytest.mark.parametrize('path', ['/api/public/guitars?viewer_id=2', '/api/public/guitars/0',
    '/api/public/guitars/1?include=photos', '/api/public/guitars/1/chronicle?after=0',
    '/api/public/guitars/1/chronicle?limit=51', '/api/public/guitars/1/chronicle?after=1&after=2',
    '/api/public/guitars/1/chronicle?q=test', '/api/public/guitars/9223372036854775808'])
def test_bad_api_inputs_never_read(api, path):
    client, _, service = api
    assert client.get(path).status_code == 400
    service.list.assert_not_called(); service.detail.assert_not_called(); service.chronicle.assert_not_called()


@pytest.mark.parametrize('error,status', [(GuitarMissing(),404), (ServiceRestricted('PRIVATE'),403),
    (PermissionError('PRIVATE'),403), (RuntimeError('gs://PRIVATE'),503)])
def test_errors_do_not_leak_private_data(api, error, status):
    client, _, service = api
    service.detail.side_effect = error
    response = client.get('/api/public/guitars/1')
    assert response.status_code == status and 'PRIVATE' not in response.text
    assert response.headers['cache-control'] == 'private, no-store'
    if isinstance(error, ServiceRestricted):
        assert response.json()['detail']['code'] == 'service_restricted'


def test_http_boundary_reapplies_allowlist_even_if_service_changes(api):
    client, _, service = api
    secret = dict(current_owner_name='PRIVATE', body='PRIVATE', evidence={'secret':'PRIVATE'}, photo='gs://PRIVATE')
    value = 2**63-1
    service.detail.return_value = dict(id=value, specifications=[{'field_name':'neck','value_text':'Maple', 'secret':'PRIVATE'},
        {'field_name':'account_email','value_text':'PRIVATE'}], **secret)
    response = client.get('/api/public/guitars/'+str(value))
    assert response.json()['id'] == str(value) and response.json()['photo'] is None
    assert response.json()['specifications'] == [{'field_name':'neck','value_text':'Maple'}]
    assert 'PRIVATE' not in response.text
    service.chronicle.return_value = {'items':[dict(id=value,claim_type='event',verification_status='negative',
        **secret), dict(id=1,claim_type='unknown',verification_status='positive')], 'next_after':value, 'private':'PRIVATE'}
    response = client.get('/api/public/guitars/1/chronicle')
    assert 'PRIVATE' not in response.text and len(response.json()['items']) == 1
    assert response.json()['items'][0]['items'] == [] and response.json()['next_after'] == str(value)


@pytest.mark.parametrize('path', ['/api/public/guitars', '/api/public/guitars/1', '/api/public/guitars/1/chronicle'])
@pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete'])
def test_public_routes_never_mutate(api, path, method):
    client, _, service = api
    assert getattr(client, method)(path).status_code == 405
    assert not service.mock_calls


class Connection:
    def __init__(self, results):
        self.results, self.calls = iter(results), []
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        cursor = Mock()
        if not sql.startswith('SET '):
            result = next(self.results)
            cursor.fetchone.return_value = result
            cursor.fetchall.return_value = result
        return cursor


@pytest.fixture
def service(monkeypatch):
    from ygc import cloud_public_catalog as module
    ops = Mock(); lock = {'held':False}
    @contextmanager
    def access(kind, actor):
        assert kind == 'public_read'
        lock['held'] = True
        try: yield
        finally: lock['held'] = False
    ops.access.side_effect = access
    @contextmanager
    def connection(settings, target):
        assert lock['held'] and target == 'chronicle'
        yield lock['connection']
        assert lock['held']
    monkeypatch.setattr(module, 'connect', connection)
    return CloudPublicCatalog(None, ops), ops, lock


def test_list_is_fenced_readonly_literal_search_and_allowlisted_sql(service):
    catalog, ops, lock = service
    con = lock['connection'] = Connection([{'total':27}, [dict(id=2,manufacturer='Maker')]])
    page = catalog.list(None, q='%_\\', sort='maker', page=2, limit=24)
    assert page == dict(items=[guitar_projection(dict(id=2,manufacturer='Maker'))],total='27',page=2,page_size=24,total_pages=2)
    assert not lock['held']
    assert [sql for sql, _ in con.calls[:3]] == ['SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY',
        "SET LOCAL statement_timeout='5s'", "SET LOCAL lock_timeout='2s'"]
    sql, params = con.calls[-1]
    assert params[-2:] == (24,24) and params[2] == '%\\%\\_\\\\%'
    assert "u.ban_status='normal'" in sql and "c.status='active'" in sql
    assert 'i.id ASC' in sql and 'FOR UPDATE' not in sql
    assert not any(word in sql for word in ('current_owner','location','media_assets','applications','payload_json'))


def test_detail_missing_and_private_spec_fields_are_never_selected(service):
    catalog, _, lock = service
    con = lock['connection'] = Connection([dict(id=1,manufacturer='Maker'), [dict(field_name='neck',value_text='Maple')], {'current_owner_user_id':None,'current_owner_name':None}, None, None, []])
    assert catalog.detail(None, 1)['specifications'] == [{'field_name':'neck','value_text':'Maple'}]
    sql, params = con.calls[-5]
    assert params == (1,list(SPEC_FIELDS),list(SPEC_FIELDS)) and "c.verification_status='positive'" in sql
    assert 'UNION ALL' in sql and 'COALESCE(occurred_at,created_at)' in sql
    assert 'author_name' not in sql and 'c.body' not in sql
    lock['connection'] = Connection([None])
    with pytest.raises(GuitarMissing): catalog.detail(None,1)


@pytest.mark.parametrize('kwargs', [{'page':True}, {'page':0}, {'limit':51}, {'sort':'sql'}, {'q':'x'*121}, {'q':'\x00'}])
def test_service_validates_before_operation_or_db(service, kwargs):
    catalog, ops, _ = service
    with pytest.raises(ValueError): catalog.list(**kwargs)
    ops.access.assert_not_called()


def test_negative_unverified_chronicle_never_reads_evidence_or_claim_items(service):
    catalog, _, lock = service
    con = lock['connection'] = Connection([dict(id=1), [dict(id=3,author_user_id=None,claim_type='ownership',verification_status='negative'),
        dict(id=2,author_user_id=None,claim_type='event',verification_status='unverified'), dict(id=1,claim_type='listing',verification_status='positive')], []])
    result = catalog.chronicle(None,1,limit=2)
    assert result['next_after'] == '2' and all(row['items'] == [] and row['source_url'] is None for row in result['items'])
    assert not any('claim_source_evidence' in sql or 'claim_spec_items' in sql for sql, _ in con.calls)


def test_public_read_service_mode_denial_prevents_chronicle_database(service):
    catalog, ops, lock = service
    ops.access.side_effect = ServiceRestricted('blocked')
    with pytest.raises(ServiceRestricted): catalog.list(None)
    assert 'connection' not in lock


@pytest.mark.parametrize('field', ['manufacturer','model','finish','year','serial_number'])
@pytest.mark.parametrize('direction', ['asc','desc'])
def test_formal_heading_sorts_only_existing_public_fields(service, field, direction):
    catalog, _, lock = service
    con = lock['connection'] = Connection([{'total':0}, []])
    catalog.list(None, q='Sunburst 1960', sort=field+'_'+direction)
    sql, params = con.calls[-1]
    assert "concat_ws(' ', i.manufacturer, i.model, i.finish, i.year, i.serial_number) ILIKE %s" in sql
    assert 'lower(i.'+field+')' in sql
    assert 'COLLATE "C" '+direction.upper()+', i.id ASC' in sql
    assert params[2] == '%Sunburst 1960%'
    assert len(params) == 5
    assert not any(key in sql for key in ('current_owner', 'location', 'payload_json', 'media_assets'))


def test_public_photo_route_checks_identity_and_never_accepts_storage_paths(api):
    client,verifier,service=api
    service.photo.return_value=b'image-fixture'
    result=client.get('/api/public/guitars/1/photo')
    assert result.status_code==200 and result.headers['content-type']=='image/jpeg'
    assert result.headers['cache-control']=='private, no-store'
    service.photo.assert_called_once_with(None,1)
    assert client.get('/api/public/guitars/1/photo?storage_path=secret').status_code==400
    service.photo.side_effect=GuitarMissing()
    assert client.get('/api/public/guitars/1/photo').status_code==404


@pytest.mark.parametrize('count', ['-1', '1.2', True, '01', '9223372036854775808', None])
def test_invalid_public_claim_count(count):
    with pytest.raises(ValueError):
        guitar_projection({'id': 1, 'claim_count': count})


def test_public_claim_count_preserves_large_integer():
    assert guitar_projection({'id': 1, 'claim_count': '9007199254740993'})['claim_count'] == '9007199254740993'


@pytest.mark.parametrize('path,method', [('/api/public/guitars','list'),('/api/public/guitars/1','detail'),('/api/public/guitars/1/chronicle','chronicle')])
def test_conditional_public_reads_reauthorize_and_compare_completed_projection(api,path,method):
    client,verifier,service=api
    first=client.get(path,headers={'Authorization':'Bearer valid'})
    tag=first.headers['etag'];assert len(tag)==66
    second=client.get(path,headers={'Authorization':'Bearer valid','If-None-Match':tag})
    assert second.status_code==304 and second.content==b''
    assert second.headers['vary']=='Authorization' and 'no-cache' in second.headers['cache-control']
    assert getattr(service,method).call_count==2 and verifier.verify.call_count==2
    verifier.accounts.resolve_identity.side_effect=PermissionError()
    rejected=client.get(path,headers={'Authorization':'Bearer valid','If-None-Match':tag})
    assert rejected.status_code==403 and rejected.headers['cache-control']=='private, no-store'
    assert 'etag' not in rejected.headers

@pytest.mark.parametrize('error,status',[(GuitarMissing(),404),(ServiceRestricted('PRIVATE'),403),(RuntimeError('PRIVATE'),503)])
def test_conditional_read_never_uses_old_payload_after_denial_or_failure(api,error,status):
    client,_,service=api;tag=client.get('/api/public/guitars/1').headers['etag']
    service.detail.side_effect=error
    response=client.get('/api/public/guitars/1',headers={'If-None-Match':tag})
    assert response.status_code==status and 'no-store' in response.headers['cache-control']
    assert 'etag' not in response.headers and 'PRIVATE' not in response.text

def test_public_etag_tracks_visible_fields_and_ignores_private_service_extras(api):
    client,_,service=api;path='/api/public/guitars/1';first=client.get(path);tag=first.headers['etag']
    service.detail.return_value['private_evidence']='PRIVATE'
    assert client.get(path,headers={'If-None-Match':'W/'+tag}).status_code==304
    service.detail.return_value['manufacturer']='Changed'
    response=client.get(path,headers={'If-None-Match':tag})
    assert response.status_code==200 and response.json()['manufacturer']=='Changed' and response.headers['etag']!=tag
    assert 'PRIVATE' not in response.text
