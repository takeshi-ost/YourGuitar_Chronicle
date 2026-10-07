"""Disposable Event service/HTTP regressions; no credentials, sockets or real photos."""
from contextlib import contextmanager
from io import BytesIO
import json
import sqlite3
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from test_cloud_claims import services
from test_cloud_media_claims import Storage, photo
from ygc.claim_revision import ClaimConflict
from ygc.cloud_avatar import ImageUploadInvalid
from ygc.cloud_claims import EVENT_KINDS, payload
from ygc.cloud_claim_routes import claim_router
from ygc.cloud_content_media import decode_reference, encode_reference
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_media_claim_routes import media_claim_router, MediaParser
from ygc.cloud_owner_routes import owner_router
from ygc.cloud_public_catalog import claim_projection
from ygc.cloud_storage import ObjectReference
from ygc.db.postgres_operations import ServiceRestricted
from ygc.identity_platform import VerifiedIdentity

EVENT = dict(claim_type='event', event_kind='performance', body='Private venue and performance details.',
             occurred_at='2020-03-01')
AUTH = {'Authorization': 'Bearer fixture'}


@pytest.fixture
def event(services):
    services[1].storage = Storage()
    return services


def create(service, user, guitar, count=1, **changes):
    return service.create_event(user, guitar, EVENT | changes, [(photo(), 'image/png')] * count)['claim']


@pytest.mark.parametrize('kind', EVENT_KINDS)
@pytest.mark.parametrize('count', [0, 1, 10])
def test_all_event_kinds_optional_private_photos_and_complete_owner_projection(event, kind, count):
    repo, service, owner, a, b, c, guitar = event
    before = repo.get_individual(guitar)[0]
    row = create(service, b, guitar, count, event_kind=kind)
    assert row['event_kind'] == kind and row['verification_status'] == 'unverified'
    assert row['spec_items'] == [] and row['incident_kind'] is None and row['specification_kind'] is None
    assert row['field_name'] == 'event_kind' and row['value_text'] == kind
    assert len(row['media_items']) == count and len(service.storage.puts) == count
    assert all(set(item) == {'id', 'mime_type'} for item in row['media_items'])
    assert not any(word in json.dumps(row) for word in ('storage_path', 'gcs-content', 'original_filename', 'author_user_id'))
    assert service.list(b, guitar)['items'] == [row] and service.list(c, guitar)['items'] == []
    reviewed = owner.pending(a, guitar)['items'][0]
    assert reviewed['body'] == EVENT['body'] and reviewed['value_text'] == kind and reviewed['event_kind'] == kind
    assert reviewed['revision'] == row['revision'] and reviewed['media_items'] == row['media_items']
    assert owner.pending(b, guitar)['items'] == []
    owner.respond(a, guitar, int(row['id']), dict(stance='positive', revision=row['revision']))
    for key in ('manufacturer', 'model', 'serial_number', 'current_owner_user_id', 'location_country', 'location_region'):
        assert repo.get_individual(guitar)[0][key] == before[key]
    assert create(service, a, guitar, 0, event_kind=kind)['verification_status'] == 'positive'
    with repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM notifications WHERE notification_type='claim_added'").fetchone()[0] == 1


def test_text_only_json_and_multipart_service_need_no_storage(event):
    repo, service, owner, a, b, c, guitar = event
    service.storage = None
    assert service.create(b, guitar, EVENT)['claim']['media_items'] == []
    assert create(service, b, guitar, 0)['media_items'] == []
    with pytest.raises(ValueError):
        create(service, b, guitar)


@pytest.mark.parametrize('changes', [dict(event_kind='lost'), dict(event_kind=None), dict(event_kind=[]),
    dict(event_kind='Performance'), dict(body=''), dict(body=None), dict(body='  '), dict(body='x'*2001),
    dict(body='bad\0value'), dict(body=True), dict(occurred_at=None), dict(occurred_at=''),
    dict(occurred_at='2999-01-01'), dict(occurred_at=True), dict(author_user_id=1),
    dict(verification_status='positive'), dict(media_items=[]), dict(storage_path='private'),
    dict(claim_type='ownership')])
def test_event_strict_payload_rejects_overposting_or_missing_detail_and_date(event, changes):
    repo, service, owner, a, b, c, guitar = event
    for editing in (False, True):
        with pytest.raises(ValueError):
            payload(EVENT | changes | ({'revision': 'a'*64} if editing else {}), editing=editing)
    with pytest.raises(ValueError):
        create(service, b, guitar, **changes)
    assert service.storage.puts == []


def test_author_edit_preserves_subtype_photos_verification_and_deactivate_is_soft(event):
    repo, service, owner, a, b, c, guitar = event
    row = create(service, b, guitar, 2)
    cid, mid = int(row['id']), int(row['media_items'][0]['id'])
    owner.respond(a, guitar, cid, dict(stance='positive', revision=row['revision']))
    row = service.list(b, guitar)['items'][0]
    for user in (a, c):
        with pytest.raises(GuitarMissing):
            service.edit(user, guitar, cid, EVENT | {'revision': row['revision']})
        with pytest.raises(GuitarMissing):
            service.deactivate(user, guitar, cid, {'revision': row['revision']})
    with pytest.raises(ValueError):
        service.edit(b, guitar, cid, EVENT | {'revision': row['revision'], 'event_kind': 'other'})
    updated = service.edit(b, guitar, cid, EVENT | {'revision': row['revision'],
                           'body': 'Updated private detail', 'occurred_at': '2020-02-15'})['claim']
    assert updated['verification_status'] == 'positive' and updated['event_kind'] == 'performance'
    assert updated['media_items'] == row['media_items'] and len(service.storage.puts) == 2
    assert updated['occurred_at'] == '2020-02-15'
    with pytest.raises(ClaimConflict):
        service.image(a, guitar, cid, mid, row['revision'])
    dead = service.deactivate(b, guitar, cid, {'revision': updated['revision']})['claim']
    assert dead['status'] == 'inactive' and service.image(b, guitar, cid, mid, dead['revision'])
    with pytest.raises(GuitarMissing):
        service.image(a, guitar, cid, mid, dead['revision'])
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, cid, dict(stance='positive', revision=dead['revision']))
    assert service.storage.deletes == []
    with repo.connect() as con:
        con.execute("UPDATE claims SET status='inactive' WHERE individual_id=?", (guitar,))
    assert service.list(b, guitar)['items'] == [dead]
    with pytest.raises(GuitarMissing):
        service.list(c, guitar)


@pytest.mark.parametrize('change', ['body', 'generation', 'remove', 'attach'])
def test_complete_revision_changes_reject_stale_owner_author_and_photo_reads(event, monkeypatch, change):
    repo, service, owner, a, b, c, guitar = event
    monkeypatch.setattr('ygc.db.repository.utcnow', lambda: '2020-03-01T00:00:00+00:00')
    row = create(service, b, guitar)
    cid, mid = int(row['id']), int(row['media_items'][0]['id'])
    with repo.connect() as con:
        if change == 'body':
            con.execute("UPDATE claims SET body='Changed without timestamp update' WHERE id=?", (cid,))
        elif change == 'generation':
            ref = decode_reference(con.execute('SELECT storage_path FROM media_assets WHERE id=?', (mid,)).fetchone()[0])
            con.execute('UPDATE media_assets SET storage_path=? WHERE id=?',
                        (encode_reference(ObjectReference(ref.scope, ref.name, ref.generation + 1, ref.size, ref.content_type)), mid))
        elif change == 'remove':
            con.execute('DELETE FROM claim_evidence WHERE claim_id=?', (cid,))
        else:
            ref = service.storage.put('content', photo('JPEG'), content_type='image/jpeg')
            added = con.execute("INSERT INTO media_assets(individual_id,uploader_user_id,storage_path,mime_type,created_at,updated_at) VALUES(?,?,?,'image/jpeg','2020','2020')", (guitar,b,encode_reference(ref))).lastrowid
            con.execute("INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(?,?,'2020')", (cid,added))
    current = service.list(b, guitar)['items'][0]
    assert current['revision'] != row['revision'] and current['updated_at'] == row['updated_at']
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, cid, dict(stance='positive', revision=row['revision']))
    with pytest.raises(ClaimConflict):
        service.edit(b, guitar, cid, EVENT | {'revision': row['revision']})
    with pytest.raises(ClaimConflict):
        service.deactivate(b, guitar, cid, {'revision': row['revision']})
    with pytest.raises((ClaimConflict, GuitarMissing)):
        service.image(a, guitar, cid, mid, row['revision'])
    assert not service.storage.gets


def test_photos_normalized_bound_to_claim_and_revoked_by_owner_change_or_ban(event):
    repo, service, owner, a, b, c, guitar = event
    row = service.create_event(b, guitar, EVENT, [(photo(size=(2800,100)), 'image/png')])['claim']
    cid, mid = int(row['id']), int(row['media_items'][0]['id'])
    other = create(service, b, guitar)
    for user, claim, asset in ((c,cid,mid),(b,int(other['id']),mid),(b,cid,int(other['media_items'][0]['id']))):
        with pytest.raises(GuitarMissing):
            service.image(user, guitar, claim, asset, row['revision'])
    for user in (a,b):
        with Image.open(BytesIO(service.image(user, guitar, cid, mid, row['revision']))) as rendered:
            assert rendered.format == 'JPEG' and rendered.width == 2048 and not rendered.getexif()
    # Portable authorization regression; real agreement/locking is tested in PG.
    with repo.connect() as con:
        con.execute('UPDATE individuals SET current_owner_user_id=? WHERE id=?', (c,guitar))
    with pytest.raises(GuitarMissing):
        service.image(a, guitar, cid, mid, row['revision'])
    with pytest.raises(ClaimConflict):
        owner.respond(a, guitar, cid, dict(stance='negative', revision=row['revision']))
    assert service.image(c, guitar, cid, mid, row['revision'])
    with repo.connect() as con:
        con.execute("UPDATE users SET ban_status='silent_ban' WHERE id=?", (b,))
    assert not owner.pending(c,guitar)['items']
    with pytest.raises(GuitarMissing):
        service.image(c,guitar,cid,mid,row['revision'])
    with pytest.raises(ClaimConflict):
        owner.respond(c,guitar,cid,dict(stance='positive',revision=row['revision']))


@pytest.mark.parametrize('tamper', ['individual','uploader','shared','proof','eleven','nonimage'])
def test_malformed_or_reused_event_evidence_fail_closed(event, tamper):
    repo, service, owner, a, b, c, guitar = event
    row = create(service,b,guitar)
    cid,mid = int(row['id']),int(row['media_items'][0]['id'])
    with repo.connect() as con:
        listing = con.execute("SELECT id FROM claims WHERE claim_type='listing'").fetchone()[0]
        if tamper == 'individual':
            con.execute('PRAGMA foreign_keys=OFF')
            con.execute('UPDATE media_assets SET individual_id=? WHERE id=?',(guitar+1,mid))
        elif tamper == 'uploader':
            con.execute('UPDATE media_assets SET uploader_user_id=? WHERE id=?',(a,mid))
        elif tamper == 'shared':
            con.execute("INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(?,?,'2020')",(listing,mid))
        elif tamper == 'proof':
            proof = con.execute('SELECT media_asset_id FROM claim_evidence WHERE claim_id=?',(listing,)).fetchone()[0]
            con.execute('UPDATE claim_evidence SET media_asset_id=? WHERE claim_id=?',(proof,cid))
        elif tamper == 'nonimage':
            con.execute("UPDATE media_assets SET media_type='video' WHERE id=?",(mid,))
        else:
            for _ in range(10):
                asset = con.execute("INSERT INTO media_assets(individual_id,uploader_user_id,storage_path,created_at,updated_at) VALUES(?,?,'private','2020','2020')",(guitar,b)).lastrowid
                con.execute("INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(?,?,'2020')",(cid,asset))
    with pytest.raises(GuitarMissing):
        service.image(b,guitar,cid,mid,row['revision'])
    with pytest.raises(GuitarMissing):
        owner.pending(a,guitar)
    assert not service.storage.gets


@pytest.mark.parametrize('stance', ['positive','negative','unverified'])
def test_legacy_photos_are_private_manageable_and_cannot_support_cloud_owner_decision(event, stance):
    repo, service, owner, a, b, c, guitar = event
    cid = repo.create_event_claim(b,guitar,event_kind='other',occurred_at='2020-03-01',detail='Legacy detail',
                                 media_items=[dict(storage_path='/private/legacy.png',mime_type='image/png')])
    row = service.list(b,guitar)['items'][0]
    assert '/private/' not in json.dumps(row) and len(row['media_items']) == 1
    assert owner.pending(a,guitar)['items'][0]['media_items'] == row['media_items']
    with pytest.raises(ValueError):
        service.image(b,guitar,cid,int(row['media_items'][0]['id']),row['revision'])
    with pytest.raises(ValueError):
        owner.respond(a,guitar,cid,dict(stance=stance,revision=row['revision']))
    updated = service.edit(b,guitar,cid,EVENT | {'event_kind':'other','revision':row['revision']})['claim']
    assert updated['body'] == EVENT['body'] and not service.storage.gets and not service.storage.puts


def test_atomic_event_notification_failure_compensates_only_new_photos(event):
    repo, service, owner, a, b, c, guitar = event
    existing = create(service,b,guitar)
    with repo.connect() as con:
        before = [con.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('claims','media_assets','claim_evidence')]
        con.execute("CREATE TRIGGER fail_event_notify BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        create(service,b,guitar,2)
    with repo.connect() as con:
        assert before == [con.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('claims','media_assets','claim_evidence')]
    assert len(service.storage.deletes) == 2 and service.storage.puts[0] not in service.storage.deletes
    assert service.list(b,guitar)['items'] == [existing]


@pytest.mark.parametrize('count',[0,2])
def test_unknown_event_commit_retains_saved_claim_and_photos_without_resend(event,monkeypatch,count):
    repo, service, owner, a, b, c, guitar = event
    original = service.transaction
    @contextmanager
    def uncertain(*args,**kwargs):
        with original(*args,**kwargs) as value:
            yield value
        raise RuntimeError('Commit response interrupted')
    monkeypatch.setattr(service,'transaction',uncertain)
    with pytest.raises(RuntimeError):
        create(service,b,guitar,count)
    monkeypatch.setattr(service,'transaction',original)
    assert len(service.list(b,guitar)['items']) == 1 and len(service.storage.puts) == count
    assert not service.storage.deletes


@pytest.mark.parametrize('images', [[(b'bad','image/png')],[(photo(),'image/gif')],[(photo(),'image/jpeg')],[(photo(),'image/png')]*11])
def test_event_invalid_images_rejected_before_storage(event,images):
    repo, service, owner, a, b, c, guitar = event
    with pytest.raises(ValueError):
        service.create_event(b,guitar,EVENT,images)
    assert not service.storage.puts and service.list(b,guitar)['items'] == []


@pytest.fixture
def http(event):
    repo, service, owner, a, b, c, guitar = event
    verifier = Mock()
    verifier.verify.return_value = VerifiedIdentity('issuer','subject',None,True)
    verifier.accounts.resolve_identity.return_value = {'app_user_id':b}
    app = FastAPI()
    for router in (claim_router(verifier,service),media_claim_router(verifier,service),owner_router(verifier,owner)):
        app.include_router(router)
    with TestClient(app) as client:
        yield client,verifier,event


def upload(client,guitar,*,metadata=EVENT,images=None,headers=None,query=''):
    parts = [('metadata',(None,json.dumps(metadata) if not isinstance(metadata,str) else metadata))]
    parts += images if images is not None else [('images',('private.png',photo(),'image/png'))]
    return client.post(f'/api/auth/guitars/{guitar}/event-claims'+query,files=parts,headers=AUTH | (headers or {}))


def test_event_http_json_optional_multipart_photos_and_image_headers(http):
    client,verifier,(repo,service,owner,a,b,c,guitar) = http
    for result in (client.post(f'/api/auth/guitars/{guitar}/claims',json=EVENT,headers=AUTH),upload(client,guitar,images=[]),upload(client,guitar)):
        assert result.status_code == 200,result.text
        assert result.headers['cache-control'] == 'private, no-store' and result.headers['vary'] == 'Authorization'
        assert result.json()['claim']['event_kind'] == 'performance'
    row = result.json()['claim']
    path = f"/api/auth/guitars/{guitar}/claims/{row['id']}/media/{row['media_items'][0]['id']}?revision={row['revision']}"
    response = client.get(path,headers=AUTH)
    assert response.status_code == 200 and response.content[:2] == b'\xff\xd8'
    assert response.headers['content-type'] == 'image/jpeg' and response.headers['cross-origin-resource-policy'] == 'same-origin'
    assert client.get(path).status_code == 401
    verifier.accounts.resolve_identity.return_value = {'app_user_id':c}
    assert client.get(path,headers=AUTH).status_code == 404
    assert 'Private venue' not in client.get(path,headers=AUTH).text
    service.storage = None
    assert upload(client,guitar,images=[]).status_code == 200
    assert upload(client,guitar).status_code == 503


@pytest.mark.parametrize('metadata,images,query', [
    ('{"claim_type":"event","claim_type":"event","event_kind":"other","body":"x","occurred_at":"2020-01-01"}',None,''),
    (EVENT,[('images',('x.png',photo(),'image/png'))]*11,''),
    (EVENT,[('other',('x.png',photo(),'image/png'))],''),
    (EVENT,[('images',(None,'not a file'))],''),
    (EVENT,[('metadata',(None,'{}'))],''),(EVENT,None,'?viewer_id=3'),
    (EVENT | {'media_items':[]},None,''),(EVENT | {'claim_type':'media'},None,''),([],None,'')])
def test_event_multipart_shape_limits_and_reference_injection(http,metadata,images,query):
    client,verifier,(repo,service,owner,a,b,c,guitar) = http
    assert upload(client,guitar,metadata=metadata,images=images,query=query).status_code == 400
    assert not service.storage.puts


@pytest.mark.parametrize('headers,status',[({'Origin':'https://other.invalid'},403),
    ({'Sec-Fetch-Site':'cross-site'},403),({'Content-Encoding':'gzip'},400),
    ({'X-YGC-Timezone':'Invalid/Zone'},400),({'Content-Type':'application/json'},400)])
def test_event_transport_denials_do_not_write(http,headers,status):
    client,verifier,(repo,service,owner,a,b,c,guitar) = http
    assert upload(client,guitar,headers=headers).status_code == status
    assert not service.storage.puts


@pytest.mark.parametrize('failure,status',[(PermissionError('secret'),403),(ServiceRestricted(),403),
    (ClaimConflict('secret'),409),(GuitarMissing(),404),(ValueError('private reference'),400),(RuntimeError('private SQL'),503)])
def test_event_safe_route_errors(http,monkeypatch,failure,status):
    client,verifier,(repo,service,owner,a,b,c,guitar) = http
    monkeypatch.setattr(service,'create_event',Mock(side_effect=failure))
    response = upload(client,guitar)
    assert response.status_code == status and 'secret' not in response.text and 'private SQL' not in response.text
    assert response.headers['cache-control'] == 'private, no-store'


def test_event_wire_unicode_limit_and_spool_cleanup(http,monkeypatch):
    client,verifier,(repo,service,owner,a,b,c,guitar) = http
    parsers,original = [],MediaParser.__init__
    def init(self,*args,**kwargs):
        original(self,*args,**kwargs)
        parsers.append(self)
    monkeypatch.setattr(MediaParser,'__init__',init)
    assert upload(client,guitar,metadata=EVENT | {'body':'🎸'*2000}).status_code == 200
    assert parsers and all(file.closed for parser in parsers for file in parser._files_to_close_on_error)
    assert upload(client,guitar,metadata=' '* (32*1024+1)).status_code == 400


def test_event_public_projection_remains_summary_only(event):
    repo,service,owner,a,b,c,guitar = event
    row = create(service,b,guitar)
    public = claim_projection(row | {'author_name':'Private Person','evidence':{'secret':'private'},'photo':'gcs-private'})
    assert set(public) == {'id','claim_type','ownership_kind','occurred_at','created_at','verification_status','items','source_url'}
    assert not any(word in json.dumps(public) for word in ('Private','media_items','event_kind','revision','author','evidence','gcs-'))


def test_event_late_storage_failure_compensates_known_new_objects(event,monkeypatch):
    repo,service,owner,a,b,c,guitar = event
    original = service.storage.put
    def interrupted(*args,**kwargs):
        if service.storage.puts:
            raise RuntimeError('Second upload result unknown')
        return original(*args,**kwargs)
    monkeypatch.setattr(service.storage,'put',interrupted)
    with pytest.raises(RuntimeError):
        create(service,b,guitar,2)
    assert service.storage.deletes == service.storage.puts
    assert service.list(b,guitar)['items'] == []


def test_event_and_media_share_bounded_upload_slots(event):
    import ygc.cloud_claims as module
    repo,service,owner,a,b,c,guitar = event
    assert module.MEDIA_UPLOADS.acquire(blocking=False)
    assert module.MEDIA_UPLOADS.acquire(blocking=False)
    try:
        with pytest.raises(ClaimConflict):
            create(service,b,guitar)
        assert not service.storage.puts
    finally:
        module.MEDIA_UPLOADS.release()
        module.MEDIA_UPLOADS.release()
    with pytest.raises(ValueError):
        create(service,b,guitar,event_kind='invalid')
    assert module.MEDIA_UPLOADS.acquire(blocking=False)
    assert module.MEDIA_UPLOADS.acquire(blocking=False)
    module.MEDIA_UPLOADS.release()
    module.MEDIA_UPLOADS.release()


def test_event_total_upload_limits_before_storage_and_http_spooling(http,monkeypatch):
    import ygc.cloud_claims as claims
    import ygc.cloud_media_claim_routes as routes
    client,verifier,(repo,service,owner,a,b,c,guitar) = http
    raw = photo()
    monkeypatch.setattr(claims,'MAX_TOTAL_UPLOAD',len(raw)*2-1)
    monkeypatch.setattr(routes,'MAX_TOTAL_UPLOAD',len(raw)*2-1)
    with pytest.raises(ImageUploadInvalid):
        create(service,b,guitar,2)
    assert upload(client,guitar,images=[('images',('x.png',raw,'image/png'))]*2).status_code == 413
    assert not service.storage.puts


def test_event_identity_is_required_before_processing_files(http):
    client,verifier,(repo,service,owner,a,b,c,guitar) = http
    assert client.post(f'/api/auth/guitars/{guitar}/event-claims').status_code == 401
    verifier.verify.return_value = VerifiedIdentity('issuer','subject',None,False)
    assert upload(client,guitar).status_code == 403
    assert not service.storage.puts
