"""Synthetic private HTTP boundary tests; never access cloud data or services."""
import json
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ygc.claim_revision import ClaimConflict
from ygc.cloud_backup_preflight import BackupCapacityError
from ygc.cloud_dispute_routes import DisputeParser, MAX_BYTES, dispute_router
from ygc.cloud_guitars import GuitarMissing
from ygc.db.postgres_operations import ServiceRestricted
from ygc.identity_platform import VerifiedIdentity

BASE = '/api/auth/ownership-disputes'
ADMIN = '/api/auth/admin/ownership-disputes'
AUTH = {'Authorization': 'Bearer synthetic'}
BIG = '9007199254740993'
REV = 'a' * 64
SUBMIT = {'revision': REV, 'case_id': None, 'version': None, 'round_number': None,
          'explanation': 'Synthetic private explanation', 'summary': 'Synthetic proposed summary'}
DECISION = {'version': '1', 'round_number': '1', 'action': 'owner', 'reason': 'Synthetic decision', 'winner_claim_id': None}


@pytest.fixture
def api(monkeypatch):
    verifier, service = Mock(), Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': 'canonical', 'id': 999}
    for method in ('list', 'options', 'option', 'detail', 'acknowledge', 'submit', 'publish', 'decide'):
        getattr(service, method).return_value = {'synthetic': method}
    service.attachment.return_value = {'content': b'%PDF-1.4 synthetic', 'content_type': 'application/pdf', 'filename': 'document.pdf'}
    # Service/DTO tests cover the concrete response schema independently. These
    # tests isolate routing, request bounds, current identity, and parser cleanup.
    monkeypatch.setattr('ygc.cloud_dispute_routes.result_projection', lambda method, result: result)
    app = FastAPI()
    app.include_router(dispute_router(verifier, service))
    with TestClient(app) as client:
        yield client, verifier, service


def private(response):
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Authorization'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cross-origin-resource-policy'] == 'same-origin'


def upload(client, data=SUBMIT, *, files=None, headers=None, query=''):
    parts = [('data', (None, json.dumps(data) if not isinstance(data, str) else data))]
    parts += [('attachment', ('secret-name.pdf', b'%PDF-1.4 synthetic', 'application/pdf'))] if files is None else files
    return client.post(BASE + f'/options/{BIG}/evidence' + query, files=parts, headers=AUTH | (headers or {}))


def test_all_endpoints_resolve_current_canonical_actor_and_admin_scope(api):
    client, verifier, service = api
    reads = [(BASE, 'list', (), {'admin': False, 'after': 0, 'limit': 25, 'status': 'open'}),
             (BASE + '/options', 'options', (), {'after': 0, 'limit': 25}),
             (BASE + f'/options/{BIG}', 'option', (int(BIG),), {}),
             (BASE + '/' + BIG, 'detail', (int(BIG),), {'admin': False}),
             (ADMIN, 'list', (), {'admin': True, 'after': 0, 'limit': 25, 'status': 'open'}),
             (ADMIN + '/' + BIG, 'detail', (int(BIG),), {'admin': True})]
    for path, method, args, kwargs in reads:
        response = client.get(path, headers=AUTH)
        assert response.status_code == 200, response.text
        private(response)
        getattr(service, method).assert_called_with('canonical', *args, **kwargs)
    assert client.post(BASE + f'/options/{BIG}/acknowledge', json={'revision': REV}, headers=AUTH).status_code == 200
    service.acknowledge.assert_called_once_with('canonical', int(BIG), {'revision': REV})
    assert upload(client).status_code == 200
    service.submit.assert_called_once_with('canonical', int(BIG), SUBMIT, content=b'%PDF-1.4 synthetic', filename='secret-name.pdf')
    assert client.post(ADMIN + f'/{BIG}/decision', json=DECISION, headers=AUTH).status_code == 200
    service.decide.assert_called_once_with('canonical', int(BIG), DECISION)
    summary = {'version': '2', 'round_number': '1', 'summary': 'Reviewed summary'}
    assert client.post(ADMIN + f'/evidence/{BIG}/publish', json=summary, headers=AUTH).status_code == 200
    service.publish.assert_called_once_with('canonical', int(BIG), summary)
    assert verifier.accounts.resolve_identity.call_count == 10


@pytest.mark.parametrize('path', [BASE, BASE + '/options', BASE + '/' + BIG, ADMIN, ADMIN + '/' + BIG,
    BASE + f'/evidence/{BIG}/attachment', ADMIN + f'/evidence/{BIG}/attachment'])
def test_every_read_requires_one_verified_bearer_and_private_errors(api, path):
    client, verifier, service = api
    for headers in ({'Cookie': 'user_id=999; admin=true'}, [('Authorization', 'Bearer a'), ('Authorization', 'Bearer b')]):
        response = client.get(path, headers=headers)
        assert response.status_code == 401
        private(response)
    verifier.verify.assert_not_called()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', '', False)
    response = client.get(path, headers=AUTH)
    assert response.status_code == 403
    private(response)
    verifier.accounts.resolve_identity.assert_not_called()
    assert not service.mock_calls


@pytest.mark.parametrize('query', ['?user_id=1', '?admin=true', '?limit=51', '?limit=0', '?after=0',
    '?after=-1', '?after=9223372036854775808', '?after=١', '?after=' + '1' * 100,
    '?limit=1&limit=2', '?status=checking', '?status=open&status=all'])
def test_invalid_pagination_and_identity_queries_never_reach_service(api, query):
    client, _, service = api
    response = client.get(BASE + query, headers=AUTH)
    assert response.status_code == 400
    private(response)
    assert not service.mock_calls


def test_cursor_preserves_bigint_and_detail_rejects_query_and_body(api):
    client, _, service = api
    assert client.get(ADMIN + f'?after={BIG}&limit=50&status=all', headers=AUTH).status_code == 200
    service.list.assert_called_once_with('canonical', admin=True, after=int(BIG), limit=50, status='all')
    for path in (BASE + '/' + BIG, BASE + f'/options/{BIG}', BASE + f'/evidence/{BIG}/attachment'):
        assert client.get(path + '?admin=true', headers=AUTH).status_code == 400
        assert client.request('GET', path, headers=AUTH, content='{}').status_code == 400
    service.detail.assert_not_called()
    service.option.assert_not_called()
    service.attachment.assert_not_called()


@pytest.mark.parametrize('value', ['0', '-1', 'true', '9223372036854775808', '1' * 200, '01'])
def test_path_ids_bounded_and_canonical(api, value):
    client, _, service = api
    assert client.get(BASE + '/' + value, headers=AUTH).status_code == 400
    service.detail.assert_not_called()


@pytest.mark.parametrize('headers,status', [({'Origin': 'https://evil.invalid'}, 403),
    ({'Sec-Fetch-Site': 'cross-site'}, 403), ({'Content-Encoding': 'gzip'}, 400),
    ({'Content-Type': 'text/plain'}, 400)])
def test_cross_site_encoded_wrong_content_type_writes_rejected(api, headers, status):
    client, _, service = api
    response = client.post(ADMIN + f'/{BIG}/decision', json=DECISION, headers=AUTH | headers)
    assert response.status_code == status
    private(response)
    assert not service.mock_calls


@pytest.mark.parametrize('body', ['[]', 'null', '42', 'true', '{', '{"revision":"x","revision":"y"}'])
def test_invalid_duplicate_nonobject_json_rejected(api, body):
    client, _, service = api
    response = client.post(BASE + f'/options/{BIG}/acknowledge', content=body,
        headers=AUTH | {'Content-Type': 'application/json'})
    assert response.status_code == 400
    assert not service.mock_calls


def test_json_bounded_and_query_writes_rejected(api):
    client, _, service = api
    response = client.post(ADMIN + f'/{BIG}/decision', content=' ' * (64 * 1024 + 1),
        headers=AUTH | {'Content-Type': 'application/json'})
    assert response.status_code == 413
    private(response)
    assert client.post(ADMIN + f'/{BIG}/decision?admin=true', json=DECISION, headers=AUTH).status_code == 400
    assert not service.mock_calls


@pytest.mark.parametrize('data,files,query', [
    ('{"revision":"a","revision":"b"}', [], ''), ([], [], ''),
    (SUBMIT, [('attachment', (None, 'not a file'))], ''),
    (SUBMIT, [('attachment', ('x.pdf', b'%PDF-x', 'application/pdf'))] * 2, ''),
    (SUBMIT, [('unexpected', ('x.pdf', b'%PDF-x', 'application/pdf'))], ''),
    (SUBMIT, [('data', (None, '{}'))], ''), (SUBMIT, [], '?viewer_id=1')])
def test_multipart_shape_duplicate_fields_and_caller_identity_rejected(api, data, files, query):
    client, _, service = api
    response = upload(client, data, files=files, query=query)
    assert response.status_code == 400, response.text
    private(response)
    service.submit.assert_not_called()


def test_initial_attachment_optional_at_transport_service_enforces_round_policy(api):
    client, _, service = api
    assert upload(client, files=[]).status_code == 200
    service.submit.assert_called_once_with('canonical', int(BIG), SUBMIT)


@pytest.mark.parametrize('part', ['file', 'field', 'headers', 'total'])
def test_upload_bounds_before_spooling_or_service(api, part):
    client, _, service = api
    if part == 'file':
        response = upload(client, files=[('attachment', ('x.pdf', b'x' * (MAX_BYTES + 1), 'application/pdf'))])
    elif part == 'field':
        response = upload(client, 'x' * (64 * 1024 + 1), files=[])
    elif part == 'headers':
        response = upload(client, files=[('attachment', ('x' * 9000, b'%PDF-x', 'application/pdf'))])
    else:
        response = client.post(BASE + f'/options/{BIG}/evidence', content=b'x' * (MAX_BYTES + 100000),
            headers=AUTH | {'Content-Type': 'multipart/form-data; boundary=x'})
    assert response.status_code in (400, 413)
    private(response)
    service.submit.assert_not_called()


def test_success_failure_truncation_close_all_spools(api, monkeypatch):
    client, _, service = api
    parsers, original = [], DisputeParser.__init__
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        parsers.append(self)
    monkeypatch.setattr(DisputeParser, '__init__', init)
    assert upload(client).status_code == 200
    service.submit.side_effect = ClaimConflict('private message')
    assert upload(client).status_code == 409
    body = (b'--example\r\nContent-Disposition: form-data; name="data"\r\n\r\n' + json.dumps(SUBMIT).encode()
            + b'\r\n--example\r\nContent-Disposition: form-data; name="attachment"; filename="x.pdf"\r\n'
              b'Content-Type: application/pdf\r\n\r\n%PDF-truncated')
    assert client.post(BASE + f'/options/{BIG}/evidence', content=body,
        headers=AUTH | {'Content-Type': 'multipart/form-data; boundary=example'}).status_code == 400
    assert all(file.closed for parser in parsers for file in parser._files_to_close_on_error)


def test_cancelled_request_closes_rolled_disk_spools(api, monkeypatch):
    import anyio
    import httpx
    client, _, service = api
    parsers, original = [], DisputeParser.__init__
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        parsers.append(self)
    monkeypatch.setattr(DisputeParser, '__init__', init)
    request = httpx.Request('POST', f'http://testserver{BASE}/options/{BIG}/evidence', headers=AUTH,
        files=[('data', (None, json.dumps(SUBMIT))), ('attachment', ('x.pdf', b'x' * (2 * 1024 * 1024), 'application/pdf'))])
    body = request.read()
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST',
        'scheme': 'http', 'path': request.url.path, 'raw_path': request.url.raw_path, 'query_string': b'',
        'root_path': '', 'headers': [(k.lower(), v) for k, v in request.headers.raw],
        'server': ('testserver', 80), 'client': ('fixture', 1234)}
    async def run():
        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}
        async def send(message):
            pass
        with anyio.CancelScope() as cancellation:
            def cancel(*args, **kwargs):
                anyio.from_thread.run_sync(cancellation.cancel)
                return {'detail': {}}
            service.submit.side_effect = cancel
            await client.app(scope, receive, send)
    anyio.run(run)
    assert parsers and parsers[0]._files_to_close_on_error[0]._rolled
    assert all(file.closed for parser in parsers for file in parser._files_to_close_on_error)


def test_private_download_defensive_headers_and_current_admin_boundary(api):
    client, _, service = api
    for base, admin in ((BASE, False), (ADMIN, True)):
        response = client.get(base + f'/evidence/{BIG}/attachment', headers=AUTH)
        assert response.status_code == 200 and response.content == b'%PDF-1.4 synthetic'
        private(response)
        assert response.headers['content-disposition'] == 'attachment; filename="document.pdf"'
        assert response.headers['content-security-policy'] == "sandbox; default-src 'none'"
        service.attachment.assert_called_with('canonical', int(BIG), admin=admin)


@pytest.mark.parametrize('replacement', [{'filename': 'secret\r\nX-Leak: yes'}, {'content_type': 'text/html'},
    {'content': b''}, {'content': b'x' * (MAX_BYTES + 1)}, {'content': 'not bytes'}])
def test_download_result_validation_fails_closed(api, replacement):
    client, _, service = api
    service.attachment.return_value.update(replacement)
    response = client.get(BASE + f'/evidence/{BIG}/attachment', headers=AUTH)
    assert response.status_code == 503
    private(response)


@pytest.mark.parametrize('error,status', [(GuitarMissing, 404), (ClaimConflict, 409), (PermissionError, 403),
    (ServiceRestricted, 403), (ValueError, 400), (RuntimeError, 503)])
def test_error_details_never_escape(api, error, status):
    client, _, service = api
    service.detail.side_effect = error('secret private evidence / credential')
    response = client.get(BASE + '/' + BIG, headers=AUTH)
    assert response.status_code == status and 'secret' not in response.text
    private(response)


def test_route_always_applies_response_projection(api, monkeypatch):
    client, _, _ = api
    def reject(method, result):
        raise RuntimeError('secret DTO violation')
    monkeypatch.setattr('ygc.cloud_dispute_routes.result_projection', reject)
    response = client.get(BASE, headers=AUTH)
    assert response.status_code == 503 and 'secret' not in response.text
    private(response)


def test_legacy_storage_capacity_is_operator_blocker_without_private_sizes(api):
    client, _, service = api
    service.submit.side_effect = BackupCapacityError('legacy_evidence_line_limit',
        'legacy_evidence_preflight', {'legacy_bytes': 123456789})
    response = upload(client)
    assert response.status_code == 409
    assert response.json() == {'detail': {'code': 'dispute_storage_preflight_required'}}
    assert '123456789' not in response.text and 'legacy_bytes' not in response.text
    private(response)
