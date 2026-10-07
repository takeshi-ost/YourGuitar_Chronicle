"""Synthetic private Media service and HTTP contracts; no cloud storage writes."""
from contextlib import contextmanager
from io import BytesIO
import json
import sqlite3
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from test_cloud_claims import services  # Shared disposable Claim/Owner fixture.
from ygc.claim_revision import ClaimConflict
from ygc.cloud_avatar import ImageUploadInvalid
from ygc.cloud_claims import CloudClaims, payload
from ygc.cloud_claim_routes import claim_router
from ygc.cloud_claim_media import media_rows
from ygc.cloud_content_media import decode_reference, encode_reference
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_media_claim_routes import media_claim_router, MediaParser
from ygc.cloud_storage import ObjectReference
from ygc.db.postgres_operations import ServiceRestricted
from ygc.identity_platform import VerifiedIdentity

MEDIA = dict(claim_type='media', body='Private photo caption', occurred_at='2020-03-01')


def photo(format='PNG', size=(20, 10)):
    out = BytesIO()
    with Image.new('RGB', size, 'red') as image:
        image.save(out, format=format)
    return out.getvalue()


class Storage:
    def __init__(self):
        self.objects, self.puts, self.gets, self.deletes = {}, [], [], []

    def put(self, scope, data, *, content_type):
        ref = ObjectReference(scope, 'media/' + format(len(self.puts) + 1, '032x'),
                              31, len(data), content_type)
        self.puts.append(ref)
        self.objects[ref] = data
        return ref

    def get(self, reference):
        self.gets.append(reference)
        return self.objects[reference]

    def delete(self, reference):
        self.deletes.append(reference)
        del self.objects[reference]


@pytest.fixture
def media(services):
    services[1].storage = Storage()
    return services


def create(service, user, guitar, **changes):
    return service.create_media(user, guitar, MEDIA | changes,
                                [(photo(), 'image/png')])['claim']


def test_multi_image_creation_normalized_private_projection_and_owner_review(media):
    repo, service, owner, a, b, c, guitar = media
    raw = photo(size=(2800, 100))
    row = service.create_media(b, guitar, MEDIA,
                              [(raw, 'image/png'), (photo('JPEG'), 'image/jpeg')])['claim']
    assert row['claim_type'] == 'media' and row['verification_status'] == 'unverified'
    assert len(row['media_items']) == 2 and row['spec_items'] == []
    assert row['incident_kind'] is None and row['specification_kind'] is None
    assert row['field_name'] == 'media_type' and row['value_text'] == 'image'
    assert all(set(item) == {'id', 'mime_type'} for item in row['media_items'])
    assert not any(word in json.dumps(row) for word in ('gcs-content', 'storage_path', 'original_filename', 'uploader_user_id'))
    assert service.list(b, guitar)['items'] == [row] and service.list(c, guitar)['items'] == []
    pending = owner.pending(a, guitar)['items'][0]
    assert pending['media_items'] == row['media_items'] and pending['revision'] == row['revision']
    for user in (a, b):
        rendered = service.image(user, guitar, int(row['id']), int(row['media_items'][0]['id']), row['revision'])
        with Image.open(BytesIO(rendered)) as image:
            assert image.format == 'JPEG' and image.width == 2048 and not image.getexif()
    with repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM notifications WHERE notification_type='claim_added'").fetchone()[0] == 1
        assert con.execute('SELECT original_filename FROM media_assets WHERE id=?',
                           (int(row['media_items'][0]['id']),)).fetchone()[0] is None
    assert repo.get_individual(guitar)[0]['current_owner_user_id'] == a
    assert create(service, a, guitar)['verification_status'] == 'positive'


def test_author_edit_and_deactivate_keep_immutable_photos_and_verification(media):
    repo, service, owner, a, b, c, guitar = media
    row = create(service, b, guitar)
    cid, mid = int(row['id']), int(row['media_items'][0]['id'])
    owner.respond(a, guitar, cid, dict(stance='positive', revision=row['revision']))
    row = service.list(b, guitar)['items'][0]
    for user in (a, c):
        with pytest.raises(GuitarMissing):
            service.edit(user, guitar, cid, MEDIA | {'revision': row['revision']})
        with pytest.raises(GuitarMissing):
            service.deactivate(user, guitar, cid, {'revision': row['revision']})
    changed = service.edit(b, guitar, cid, MEDIA | {'body': 'New caption', 'occurred_at': None,
                            'revision': row['revision']})['claim']
    assert changed['verification_status'] == 'positive' and changed['occurred_at'] is None
    assert changed['media_items'] == row['media_items'] and len(service.storage.puts) == 1
    with pytest.raises(ClaimConflict):
        service.image(a, guitar, cid, mid, row['revision'])
    dead = service.deactivate(b, guitar, cid, {'revision': changed['revision']})['claim']
    assert dead['status'] == 'inactive' and service.list(b, guitar)['items'] == [dead]
    assert service.image(b, guitar, cid, mid, dead['revision'])
    with pytest.raises(GuitarMissing):
        service.image(a, guitar, cid, mid, dead['revision'])
    with pytest.raises(ClaimConflict):
        service.edit(b, guitar, cid, MEDIA | {'revision': dead['revision']})
    assert service.storage.deletes == [] and repo.get_individual(guitar)[0]['current_owner_user_id'] == a


def test_metadata_and_attachment_revisions_reject_stale_author_and_owner(media, monkeypatch):
    repo, service, owner, a, b, c, guitar = media
    monkeypatch.setattr('ygc.db.repository.utcnow', lambda: '2020-03-01T00:00:00+00:00')
    row = create(service, b, guitar)
    cid, mid = int(row['id']), int(row['media_items'][0]['id'])
    changed = service.edit(b, guitar, cid, MEDIA | {'revision': row['revision'], 'body': 'Edited'})['claim']
    assert row['updated_at'] == changed['updated_at'] and row['revision'] != changed['revision']
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, cid, dict(stance='positive', revision=row['revision']))
    with repo.connect() as con:
        previous = con.execute('SELECT storage_path FROM media_assets WHERE id=?', (mid,)).fetchone()[0]
        ref = decode_reference(previous)
        con.execute('UPDATE media_assets SET storage_path=? WHERE id=?',
                    (encode_reference(ObjectReference(ref.scope, ref.name, ref.generation + 1, ref.size, ref.content_type)), mid))
    fresh = service.list(b, guitar)['items'][0]
    assert fresh['revision'] != changed['revision']
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, cid, dict(stance='positive', revision=changed['revision']))
    with pytest.raises(ClaimConflict):
        service.deactivate(b, guitar, cid, {'revision': changed['revision']})
    assert not service.storage.gets


def test_image_is_claim_bound_author_or_current_owner_only(media):
    repo, service, owner, a, b, c, guitar = media
    row, another = create(service, b, guitar), create(service, b, guitar)
    cid, mid = int(row['id']), int(row['media_items'][0]['id'])
    for claim, asset, user in [(cid, int(another['media_items'][0]['id']), b),
                               (int(another['id']), mid, b), (cid, mid, c)]:
        with pytest.raises(GuitarMissing):
            service.image(user, guitar, claim, asset, row['revision'])
    assert service.storage.gets == []
    with repo.connect() as con:
        con.execute('UPDATE individuals SET current_owner_user_id=? WHERE id=?', (c, guitar))
    with pytest.raises(GuitarMissing):
        service.image(a, guitar, cid, mid, row['revision'])
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, cid, dict(stance='positive', revision=row['revision']))
    assert service.image(c, guitar, cid, mid, row['revision'])
    with repo.connect() as con:
        con.execute("UPDATE users SET ban_status='ban' WHERE id=?", (b,))
    with pytest.raises(GuitarMissing):
        service.image(c, guitar, cid, mid, row['revision'])
    assert row['id'] not in {item['id'] for item in owner.pending(c, guitar)['items']}
    with pytest.raises(ClaimConflict):
        owner.respond(c, guitar, cid, dict(stance='positive', revision=row['revision']))


@pytest.mark.parametrize('tamper', ['individual', 'uploader', 'shared', 'proof', 'empty', 'eleven'])
def test_invalid_or_reused_evidence_never_delivered(media, tamper):
    repo, service, owner, a, b, c, guitar = media
    row = create(service, b, guitar)
    cid, mid = int(row['id']), int(row['media_items'][0]['id'])
    with repo.connect() as con:
        listing = con.execute("SELECT id FROM claims WHERE claim_type='listing'").fetchone()[0]
        if tamper == 'individual':
            # Foreign keys are disabled only for this malformed synthetic row.
            con.execute('PRAGMA foreign_keys=OFF')
            con.execute('UPDATE media_assets SET individual_id=? WHERE id=?', (guitar + 1, mid))
        elif tamper == 'uploader':
            con.execute('UPDATE media_assets SET uploader_user_id=? WHERE id=?', (a, mid))
        elif tamper == 'shared':
            con.execute("INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(?,?,'2020-01-01')", (listing, mid))
        elif tamper == 'proof':
            proof = con.execute('SELECT media_asset_id FROM claim_evidence WHERE claim_id=?', (listing,)).fetchone()[0]
            con.execute('UPDATE claim_evidence SET media_asset_id=? WHERE claim_id=?', (proof, cid))
        elif tamper == 'empty':
            con.execute('DELETE FROM claim_evidence WHERE claim_id=?', (cid,))
        else:
            for n in range(10):
                asset = con.execute("INSERT INTO media_assets(individual_id,uploader_user_id,storage_path,created_at,updated_at) VALUES(?,?,'private','2020','2020')", (guitar,b)).lastrowid
                con.execute("INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(?,?,'2020')", (cid,asset))
    with pytest.raises(GuitarMissing):
        service.image(b, guitar, cid, mid, row['revision'])
    assert service.storage.gets == []


def test_legacy_local_path_stays_private_and_metadata_manageable(media):
    repo, service, owner, a, b, c, guitar = media
    cid, mid = repo.create_media_claim(b, guitar, storage_path='/private/legacy.jpg',
                                      mime_type='image/jpeg', occurred_at='2020-03-01')
    row = service.list(b, guitar)['items'][0]
    assert '/private/' not in json.dumps(row)
    with pytest.raises(ValueError):
        service.image(b, guitar, cid, mid, row['revision'])
    edited = service.edit(b, guitar, cid, MEDIA | {'revision': row['revision']})['claim']
    assert edited['body'] == MEDIA['body'] and service.storage.gets == []


def test_atomic_notification_failure_compensates_new_images_only(media):
    repo, service, owner, a, b, c, guitar = media
    existing = create(service, a, guitar)
    previous = service.storage.puts[:]
    with repo.connect() as con:
        before = tuple(con.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                       for table in ('claims', 'media_assets', 'claim_evidence'))
        con.execute("CREATE TRIGGER fail_media_notify BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.create_media(b, guitar, MEDIA, [(photo(), 'image/png')] * 2)
    with repo.connect() as con:
        after = tuple(con.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                      for table in ('claims', 'media_assets', 'claim_evidence'))
    assert before == after and len(service.storage.deletes) == 2
    assert all(ref not in service.storage.deletes for ref in previous)
    assert service.list(a, guitar)['items'] == [existing]


def test_late_storage_failure_compensates_only_known_new_generations(media, monkeypatch):
    repo, service, owner, a, b, c, guitar = media
    real_put = service.storage.put
    def put(*args, **kwargs):
        if service.storage.puts:
            raise RuntimeError('Uncertain second object upload')
        return real_put(*args, **kwargs)
    monkeypatch.setattr(service.storage, 'put', put)
    with pytest.raises(RuntimeError):
        service.create_media(b, guitar, MEDIA, [(photo(), 'image/png')] * 2)
    assert service.storage.deletes == service.storage.puts and service.list(b, guitar)['items'] == []


def test_uncertain_commit_retains_objects_and_does_not_resend(media, monkeypatch):
    repo, service, owner, a, b, c, guitar = media
    original = service.transaction
    @contextmanager
    def uncertain(*args, **kwargs):
        with original(*args, **kwargs) as value:
            yield value
        raise RuntimeError('Committed, response interrupted')
    monkeypatch.setattr(service, 'transaction', uncertain)
    with pytest.raises(RuntimeError):
        create(service, b, guitar)
    assert len(service.storage.puts) == 1 and service.storage.deletes == []
    monkeypatch.setattr(service, 'transaction', original)
    row = service.list(b, guitar)['items'][0]
    assert service.image(b, guitar, int(row['id']), int(row['media_items'][0]['id']), row['revision'])


@pytest.mark.parametrize('change', [dict(author_user_id=1), dict(media_items=[]), dict(storage_path='gcs-content-v1:private'),
    dict(verification_status='positive'), dict(body='x'*2001), dict(body='bad\x00value'),
    dict(occurred_at='2999-01-01'), dict(occurred_at=True), dict(body=[]), dict(claim_type='ownership')])
def test_media_payload_rejects_overposting_and_invalid_values(media, change):
    repo, service, owner, a, b, c, guitar = media
    with pytest.raises((ValueError, TypeError)):
        create(service, b, guitar, **change)
    assert not service.storage.puts


@pytest.mark.parametrize('images', [[], [(b'not a photo', 'image/png')], [(photo(), 'image/jpeg')],
    [(photo(), 'image/gif')], [(photo(), 'image/png')] * 11])
def test_invalid_images_are_rejected_before_storage(media, images):
    repo, service, owner, a, b, c, guitar = media
    with pytest.raises(ValueError):
        service.create_media(b, guitar, MEDIA, images)
    assert not service.storage.puts


def test_ten_images_and_hidden_inactive_author_history(media):
    repo, service, owner, a, b, c, guitar = media
    row = service.create_media(b, guitar, MEDIA, [(photo(), 'image/png')] * 10)['claim']
    assert len(row['media_items']) == 10
    with repo.connect() as con:
        con.execute("UPDATE claims SET status='inactive' WHERE individual_id=?", (guitar,))
        from ygc.db.postgres_ownership import BoundRepository
        from test_cloud_claims import SQLiteConnection
        bound = BoundRepository(SQLiteConnection(con))
        assert service._individual(bound, guitar, b)['id'] == str(guitar)
        with pytest.raises(GuitarMissing):
            service._individual(bound, guitar, c)


@pytest.fixture
def http(media):
    repo, service, owner, a, b, c, guitar = media
    verifier = Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', None, True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id': b}
    app = FastAPI()
    app.include_router(media_claim_router(verifier, service))
    app.include_router(claim_router(verifier, service))
    return TestClient(app), verifier, media


def upload(client, guitar, *, metadata=MEDIA, images=None, headers=None, query=''):
    parts = [('metadata', (None, json.dumps(metadata) if not isinstance(metadata, str) else metadata))]
    parts += images if images is not None else [('images', ('private-filename.png', photo(), 'image/png'))]
    return client.post(f'/api/auth/guitars/{guitar}/media-claims' + query,
        files=parts, headers={'Authorization': 'Bearer fixture', **(headers or {})})


def test_private_multipart_create_edit_image_deactivate_headers(http):
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    result = upload(client, guitar)
    assert result.status_code == 200, result.text
    row = result.json()['claim']
    url = f"/api/auth/guitars/{guitar}/claims/{row['id']}/media/{row['media_items'][0]['id']}?revision={row['revision']}"
    image = client.get(url, headers={'Authorization': 'Bearer fixture'})
    assert image.status_code == 200 and image.headers['content-type'] == 'image/jpeg'
    assert image.content[:2] == b'\xff\xd8'
    for response in (result, image, client.get(url)):
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Authorization'
        assert response.headers['x-content-type-options'] == 'nosniff'
    assert client.get(url).status_code == 401
    edited = client.patch(f"/api/auth/guitars/{guitar}/claims/{row['id']}",
        headers={'Authorization': 'Bearer fixture'}, json=MEDIA | {'body': 'Updated', 'revision': row['revision']})
    assert edited.status_code == 200 and edited.json()['claim']['media_items'] == row['media_items']
    assert client.get(url, headers={'Authorization':'Bearer fixture'}).status_code == 409
    assert client.post(f'/api/auth/guitars/{guitar}/claims', headers={'Authorization':'Bearer fixture'}, json=MEDIA).status_code == 400


@pytest.mark.parametrize('headers,status', [({'Origin':'https://other.invalid'},403),
    ({'Sec-Fetch-Site':'cross-site'},403), ({'Content-Encoding':'gzip'},400),
    ({'X-YGC-Timezone':'Invalid/Zone'},400), ({'Content-Type':'application/json'},400)])
def test_multipart_transport_boundaries(http, headers, status):
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    response = upload(client, guitar, headers=headers)
    assert response.status_code == status and not service.storage.puts


@pytest.mark.parametrize('metadata,images,query', [
    ('{"claim_type":"media","claim_type":"media","body":null,"occurred_at":null}', None, ''),
    (MEDIA, [], ''), (MEDIA, [('images',('x.png',photo(),'image/png'))]*11, ''),
    (MEDIA, [('other',('x.png',photo(),'image/png'))], ''),
    (MEDIA, [('images',('x.png',photo(),'image/png')),('metadata',(None,'{}'))], ''),
    (MEDIA, [('images',(None,'not a file'))], ''), (MEDIA, None, '?surprise=1'),
    (MEDIA | {'storage_path':'private'}, None, ''), ([], None, '')])
def test_strict_form_shape_and_no_reference_injection(http, metadata, images, query):
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    response = upload(client, guitar, metadata=metadata, images=images, query=query)
    assert response.status_code == 400 and service.storage.puts == []


def test_form_spools_closed_after_success_and_truncated_final_part(http, monkeypatch):
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    parsers, original = [], MediaParser.__init__
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        parsers.append(self)
    monkeypatch.setattr(MediaParser, '__init__', init)
    assert upload(client, guitar).status_code == 200
    body = (b'--example\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n' + json.dumps(MEDIA).encode()
            + b'\r\n--example\r\nContent-Disposition: form-data; name="images"; filename="x.png"\r\nContent-Type: image/png\r\n\r\n'
            + photo() + b'\r\n--example\r\nContent-Disposition: form-data; name="images"; filename="unfinished.png"\r\nContent-Type: image/png\r\n\r\ntruncated')
    response = client.post(f'/api/auth/guitars/{guitar}/media-claims', content=body,
        headers={'Authorization':'Bearer fixture','Content-Type':'multipart/form-data; boundary=example'})
    assert response.status_code == 400 and len(service.storage.puts) == 1
    assert all(file.closed for parser in parsers for file in parser._files_to_close_on_error)


def test_cancelled_request_closes_rolled_spools_after_parsing(http, monkeypatch):
    import anyio
    import httpx
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    parsers, original = [], MediaParser.__init__
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        parsers.append(self)
    monkeypatch.setattr(MediaParser, '__init__', init)
    request = httpx.Request('POST', f'http://testserver/api/auth/guitars/{guitar}/media-claims',
        headers={'Authorization': 'Bearer fixture'}, files=[('metadata', (None, json.dumps(MEDIA))),
            ('images', ('fixture.png', b'x' * (2 * 1024 * 1024), 'image/png'))])
    body = request.read()
    scope = {'type': 'http', 'asgi': {'version':'3.0'}, 'http_version': '1.1',
        'method': 'POST', 'scheme': 'http', 'path': request.url.path, 'raw_path': request.url.raw_path,
        'query_string': b'', 'root_path':'', 'headers': [(k.lower(), v) for k, v in request.headers.raw],
        'server': ('testserver', 80), 'client': ('fixture', 1234)}
    async def run():
        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}
        async def send(message):
            pass
        with anyio.CancelScope() as cancellation:
            def cancel_after_parse(*args):
                anyio.from_thread.run_sync(cancellation.cancel)
                return {'claim': {}}
            monkeypatch.setattr(service, 'create_media', cancel_after_parse)
            await client.app(scope, receive, send)
    anyio.run(run)
    assert parsers and parsers[0]._files_to_close_on_error[0]._rolled
    assert all(file.closed for parser in parsers for file in parser._files_to_close_on_error)


def test_concurrent_upload_admission_rejects_before_normalization_and_releases(media, monkeypatch):
    import ygc.cloud_claims as module
    repo, service, owner, a, b, c, guitar = media
    assert module.MEDIA_UPLOADS.acquire(blocking=False)
    assert module.MEDIA_UPLOADS.acquire(blocking=False)
    entered = Mock(side_effect=AssertionError('Busy request must not normalize or write.'))
    original = service._create_media
    monkeypatch.setattr(service, '_create_media', entered)
    try:
        with pytest.raises(ClaimConflict):
            create(service, b, guitar)
        entered.assert_not_called()
    finally:
        module.MEDIA_UPLOADS.release()
        module.MEDIA_UPLOADS.release()
    monkeypatch.setattr(service, '_create_media', original)
    with pytest.raises(ValueError):
        service.create_media(b, guitar, MEDIA, [])
    assert create(service, b, guitar)['claim_type'] == 'media'
    assert module.MEDIA_UPLOADS.acquire(blocking=False)
    assert module.MEDIA_UPLOADS.acquire(blocking=False)
    module.MEDIA_UPLOADS.release()
    module.MEDIA_UPLOADS.release()


def test_oversized_file_is_rejected_while_streaming(http, monkeypatch):
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    import ygc.cloud_media_claim_routes as routes
    monkeypatch.setattr(routes, 'MAX_UPLOAD', 1024)
    response = upload(client, guitar, images=[('images', ('large.png', b'x'*1025, 'image/png'))])
    assert response.status_code == 413 and response.json()['detail']['code'] == 'image_size_limit'
    assert not service.storage.puts


def test_combined_image_bound_is_enforced_by_service_and_stream(http, monkeypatch):
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    import ygc.cloud_claims as claims
    import ygc.cloud_media_claim_routes as routes
    raw = photo()
    monkeypatch.setattr(claims, 'MAX_TOTAL_UPLOAD', len(raw) * 2 - 1)
    monkeypatch.setattr(routes, 'MAX_TOTAL_UPLOAD', len(raw) * 2 - 1)
    with pytest.raises(ImageUploadInvalid):
        service.create_media(b, guitar, MEDIA, [(raw, 'image/png')] * 2)
    response = upload(client, guitar, images=[('images', ('x.png', raw, 'image/png'))] * 2)
    assert response.status_code == 413 and not service.storage.puts


@pytest.mark.parametrize('part', ['metadata', 'header'])
def test_multipart_metadata_and_headers_have_separate_limits(http, part):
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    if part == 'metadata':
        response = upload(client, guitar, metadata=' ' * (16 * 1024 + 1))
    else:
        response = upload(client, guitar, images=[('images', ('x' * 8193, photo(), 'image/png'))])
    assert response.status_code == 400 and not service.storage.puts


@pytest.mark.parametrize('failure,status', [(PermissionError('secret'),403),
    (ServiceRestricted(),403), (ClaimConflict('secret'),409), (GuitarMissing(),404),
    (ValueError('private storage reference'),400), (RuntimeError('private SQL'),503)])
def test_safe_service_failures_no_internal_values(http, monkeypatch, failure, status):
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    monkeypatch.setattr(service, 'create_media', Mock(side_effect=failure))
    response = upload(client, guitar)
    assert response.status_code == status
    assert not any(word in response.text for word in ('secret', 'storage reference', 'SQL'))
    assert response.headers['cache-control'] == 'private, no-store'


@pytest.mark.parametrize('query', ['', '?revision=bad', '?revision='+'a'*64+'&revision='+'a'*64,
                                    '?revision='+'a'*64+'&object=private'])
def test_image_requires_one_opaque_claim_revision(http, query):
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    response = client.get(f'/api/auth/guitars/{guitar}/claims/1/media/1'+query,
                          headers={'Authorization':'Bearer fixture'})
    assert response.status_code == 400 and not service.storage.gets


def test_unverified_missing_auth_and_storage_fail_closed(http):
    client, verifier, (repo, service, owner, a, b, c, guitar) = http
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', None, False)
    assert upload(client, guitar).status_code == 403
    verifier.verify.return_value = VerifiedIdentity('issuer', 'subject', None, True)
    assert client.post(f'/api/auth/guitars/{guitar}/media-claims').status_code == 401
    service.storage = None
    assert upload(client, guitar).status_code == 503
