from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ygc import cloud_catalog_insights as insights
from ygc.cloud_public_catalog import CloudPublicCatalog
from ygc.cloud_public_catalog_routes import public_catalog_router
from ygc.db.postgres_operations import ServiceRestricted
from ygc.identity_platform import VerifiedIdentity


@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical', 'role': 'member'}
    service = Mock()
    service.discoveries.return_value = {'items': [dict(id=52, manufacturer='Squier', activity_at='2026-10-12T00:00:00+00:00',
        activity_type='claim', claim_type='listing', body='PRIVATE', owner_id='PRIVATE', source_payload='PRIVATE')], 'private': 'PRIVATE'}
    service.statistics.return_value = {'individuals': '1', 'models': [{'label': 'Telecaster', 'count': '1', 'private': 'PRIVATE'}],
        'years': [{'label': '1960', 'count': '1'}], 'listings_30d': [{'date': '2026-10-12', 'count': '1'}], 'private': 'PRIVATE'}
    service.world_map.return_value = {'countries': [{'country': 'Japan', 'count': '1', 'owner_id': 'PRIVATE', 'region': 'PRIVATE'}]}
    app = FastAPI()
    app.include_router(public_catalog_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


ENDPOINTS = [('discoveries', 'discoveries'), ('statistics', 'statistics'), ('world-map', 'world_map')]


@pytest.mark.parametrize('path,method', ENDPOINTS)
def test_public_insights_allowlist_and_canonical_identity(api, path, method):
    client, verifier, service = api
    response = client.get('/api/public/guitars/' + path)
    assert response.status_code == 200 and 'PRIVATE' not in response.text
    assert response.headers['cache-control'] == 'private, no-cache, max-age=0, must-revalidate'
    assert response.headers['vary'] == 'Authorization'
    assert response.headers['x-content-type-options'] == 'nosniff'
    getattr(service, method).assert_called_once_with(None)
    verifier.verify.assert_not_called()
    assert client.get('/api/public/guitars/' + path, headers={'Authorization': 'Bearer valid'}).status_code == 200
    getattr(service, method).assert_called_with('canonical')


@pytest.mark.parametrize('path,method', ENDPOINTS)
@pytest.mark.parametrize('query', ['viewer_id=1', 'limit=201', 'after=1', 'q=x', 'country=Japan', 'limit=1&limit=2'])
def test_insights_reject_all_queries_without_reading(api, path, method, query):
    client, _, service = api
    assert client.get('/api/public/guitars/' + path + '?' + query).status_code == 400
    getattr(service, method).assert_not_called()


@pytest.mark.parametrize('path,method', ENDPOINTS)
@pytest.mark.parametrize('error,status', [(ServiceRestricted('PRIVATE'), 403), (PermissionError('PRIVATE'), 403), (RuntimeError('PRIVATE'), 503)])
def test_insights_failure_is_private_and_has_no_rows(api, path, method, error, status):
    client, _, service = api
    getattr(service, method).side_effect = error
    response = client.get('/api/public/guitars/' + path)
    assert response.status_code == status and 'PRIVATE' not in response.text
    assert response.headers['cache-control'] == 'private, no-store'


@pytest.mark.parametrize('path,method', ENDPOINTS)
@pytest.mark.parametrize('case,status', [('token', 401), ('disabled', 403), ('unverified_admin', 403)])
def test_insights_never_downgrade_rejected_identity_to_guest(api, path, method, case, status):
    client, verifier, service = api
    if case == 'token':
        verifier.verify.side_effect = PermissionError('PRIVATE')
    elif case == 'disabled':
        verifier.accounts.resolve_identity.side_effect = PermissionError('PRIVATE')
    else:
        verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
        verifier.accounts.resolve_identity.return_value['role'] = 'admin'
    response = client.get('/api/public/guitars/' + path, headers={'Authorization': 'Bearer invalid'})
    assert response.status_code == status and 'PRIVATE' not in response.text
    getattr(service, method).assert_not_called()


@pytest.mark.parametrize('value', [-1, 2**63, True, '1', 1.2])
def test_count_rejects_noncanonical_value(value):
    with pytest.raises(ValueError):
        insights.count(value)


def test_years_combine_circa_and_cha_without_extracting_ranges():
    rows = [{'label': label, 'count': amount} for label, amount in
        [('1960', 1), (' Circa 1960 ', 2), ('C.ha 1960', 3), ('1960-1962', 4), ('1960s', 5), ('Unknown', 6), ('1959', 2), ('１９６０', 1)]]
    assert insights.chart_years(rows) == [{'label': '1959', 'count': '2'}, {'label': '1960', 'count': '6'}]


def catalog_with_rows(rows):
    con = Mock()
    con.execute.side_effect = [Mock(fetchall=Mock(return_value=values), fetchone=Mock(return_value=values[0] if values else None)) for values in rows]
    catalog = CloudPublicCatalog('settings', Mock())
    @contextmanager
    def read(actor):
        assert actor == 'canonical'
        yield con
    catalog._read = read
    return catalog, con


def test_statistics_other_total_and_thirty_utc_days():
    today = datetime.now(timezone.utc).date()
    models = [{'label': str(i), 'count': 12 - i} for i in range(12)]
    catalog, _ = catalog_with_rows([[{'count': 78}], models, [{'label': 'Circa 1960', 'count': 2}],
        [{'day': today.isoformat(), 'count': 3}]])
    result = catalog.statistics('canonical')
    assert result['individuals'] == '78'
    assert len(result['models']) == 11 and result['models'][-1] == {'label': 'Other', 'count': '3'}
    assert sum(int(row['count']) for row in result['models']) == 78
    assert result['years'] == [{'label': '1960', 'count': '2'}]
    assert len(result['listings_30d']) == 30
    assert result['listings_30d'][0] == {'date': (today - timedelta(days=29)).isoformat(), 'count': '0'}
    assert result['listings_30d'][-1] == {'date': today.isoformat(), 'count': '3'}


def test_map_ignores_snapshot_for_registered_owners_and_groups_public_country(monkeypatch):
    catalog, _ = catalog_with_rows([[{'owner_id': None, 'country': 'Japan', 'count': 2},
        {'owner_id': 1, 'country': 'PRIVATE OLD', 'count': 3}, {'owner_id': 2, 'country': 'PRIVATE', 'count': 4}]])
    accounts = Mock()
    accounts.execute.return_value.fetchall.return_value = [{'id': 1, 'country': 'Japan'}]
    @contextmanager
    def connect(settings, target):
        assert settings == 'settings' and target == 'accounts'
        yield accounts
    monkeypatch.setattr(insights, 'connect', connect)
    assert catalog.world_map('canonical') == {'countries': [{'country': 'Japan', 'count': '5'}]}
    assert set(accounts.execute.call_args.args[1][0]) == {1, 2}


@pytest.mark.parametrize('method', ['discoveries', 'statistics', 'world_map'])
def test_all_insight_reads_enter_existing_service_guard_before_db(monkeypatch, method):
    operations = Mock()
    operations.access.side_effect = ServiceRestricted('offline')
    connect = Mock(side_effect=AssertionError('Must not open DB during Offline'))
    monkeypatch.setattr('ygc.cloud_public_catalog.connect', connect)
    with pytest.raises(ServiceRestricted):
        getattr(CloudPublicCatalog('settings', operations), method)('admin')
    operations.access.assert_called_once_with('public_read', 'admin')
    connect.assert_not_called()


@pytest.mark.parametrize('route,method',[('discoveries','discoveries'),('statistics','statistics'),('world-map','world_map')])
def test_insight_validation_does_not_bypass_current_service_gate(api,route,method):
    client,verifier,service=api;path='/api/public/guitars/'+route
    first=client.get(path,headers={'Authorization':'Bearer valid'});tag=first.headers['etag']
    again=client.get(path,headers={'Authorization':'Bearer valid','If-None-Match':tag})
    assert again.status_code==304 and again.content==b''
    assert verifier.verify.call_count==2 and getattr(service,method).call_count==2
    getattr(service,method).side_effect=ServiceRestricted('PRIVATE')
    denied=client.get(path,headers={'Authorization':'Bearer valid','If-None-Match':tag})
    assert denied.status_code==403 and 'no-store' in denied.headers['cache-control'] and 'etag' not in denied.headers
