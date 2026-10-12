from contextlib import contextmanager
from unittest.mock import Mock
import pytest
from ygc.cloud_public_presentation import person_projection, claim_presentation, public_people, representative
from ygc.cloud_users import CloudUsers


def test_projection_only_exposes_explicit_display_fields():
    person={'id':9007199254741009,'display_name':'<script>name</script>','email':'SECRET','avatar_storage_path':'SECRET'}
    assert person_projection(person)=={'id':'9007199254741009','display_name':'<script>name</script>'}
    result=claim_presentation({'author':person,'body':'Public prose','good_count':2,'bad_count':0,'evidence':'SECRET','challenge':'SECRET'})
    assert set(result)=={'author','body','good_count','bad_count'}
    assert 'SECRET' not in str(result)
    assert result['good_count']=='2'


def test_public_chronicle_keeps_correction_reason_private_and_preserves_public_prose(monkeypatch):
    from ygc import cloud_public_presentation as module
    monkeypatch.setattr(module, 'public_people', lambda settings, ids: {
        7: {'person': {'id': '7', 'display_name': 'Public member'}}})
    con = Mock()
    con.execute.return_value.fetchall.return_value = []
    rows = [dict(id=number, author_user_id=7, claim_type=kind,
                 body='PRIVATE correction reason' if kind == 'identity_correction' else 'Public prose')
            for number, kind in enumerate(('identity_correction', 'listing', 'specification',
                                           'incident', 'media', 'event', 'ownership'), 1)]
    module.enrich_claims(None, con, rows)
    published = [row['presentation'] for row in rows]
    assert 'PRIVATE' not in str(published)
    assert published[0]['body'] is None
    assert all(row['body'] == 'Public prose' for row in published[1:])
    assert all(row['author'] == {'id': '7', 'display_name': 'Public member'} for row in published)
    assert rows[0]['body'] == 'PRIVATE correction reason', 'Private author history must be retained'


@pytest.mark.parametrize('visibility,expected',[('Public','Japan / Tokyo'),('Members',None),('Followers',None),('Private',None),(None,None)])
def test_public_location_honors_canonical_visibility(monkeypatch,visibility,expected):
    from ygc import cloud_public_presentation as module
    con=Mock();con.execute.return_value.fetchall.return_value=[dict(id=1,display_name='Member',location_country='Japan',location_region='Tokyo',residence_visibility=visibility)]
    @contextmanager
    def connect(settings,target):
        assert target=='accounts';yield con
    monkeypatch.setattr(module,'connect',connect)
    assert public_people(None,[1])[1]['location']==expected
    sql=con.execute.call_args.args[0]
    assert "disabled=0" in sql and "ban_status='normal'" in sql
    assert 'avatar_storage_path' not in sql and 'identity_subject' not in sql


def test_representative_cannot_select_review_photos():
    con=Mock();representative(con,9)
    sql,params=con.execute.call_args.args
    assert params==(9,)
    assert 'representative_media_asset_id' in sql and "c.claim_type IN ('listing','media')" in sql
    assert "c.verification_status='positive'" in sql and "c.status='active'" in sql
    assert 'application' not in sql and 'review' not in sql


def test_self_chronicle_uses_canonical_user_and_chronological_order(monkeypatch):
    from ygc import cloud_users as module
    user=dict(id=7,display_name='Self',created_at='2020-01-01',updated_at='2020-01-01',date_of_birth='1990-01-01')
    ops=Mock()
    @contextmanager
    def access(kind,actor):
        assert (kind,actor)==('user_read','canonical');yield None,{},user
    ops.account_access.side_effect=access
    con=Mock();rows=iter([[dict(id=1,individual_id=9007199254741009,claim_type='event',ownership_kind=None,specification_kind=None,created_at='2026-10-01T00:00:00Z',manufacturer='Maker',model='Model')],[],[],[]])
    def execute(sql,params=None):
        result=Mock()
        if not sql.startswith('SET '):result.fetchall.return_value=next(rows);assert params[0]==7
        return result
    con.execute.side_effect=execute
    @contextmanager
    def connect(settings,target):assert target=='chronicle';yield con
    monkeypatch.setattr(module,'connect',connect)
    items=CloudUsers(None,ops).own_chronicle('canonical')['items']
    assert [row['category'] for row in items]==['Claim','User','User']
    assert items[0]['individual_id']=='9007199254741009'
    assert not any('evidence' in call.args[0] for call in con.execute.call_args_list)


@pytest.fixture
def photo_catalog():
    """Exercise real relational filtering without a live server or private files."""
    import sqlite3
    from ygc.cloud_public_catalog import CloudPublicCatalog
    from ygc.cloud_content_media import encode_reference
    from ygc.cloud_storage import ObjectReference
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.executescript('''
        CREATE TABLE individuals(id INTEGER PRIMARY KEY, representative_media_asset_id INTEGER);
        CREATE TABLE media_assets(id INTEGER PRIMARY KEY,individual_id INTEGER,media_type TEXT,mime_type TEXT,storage_path TEXT);
        CREATE TABLE users(id INTEGER PRIMARY KEY,ban_status TEXT,account_type TEXT);
        CREATE TABLE claims(id INTEGER PRIMARY KEY,individual_id INTEGER,author_user_id INTEGER,status TEXT,verification_status TEXT,claim_type TEXT, observation_id INTEGER, ownership_kind TEXT, occurred_at TEXT, created_at TEXT);
        CREATE TABLE claim_evidence(claim_id INTEGER,media_asset_id INTEGER);
        CREATE TABLE acquire_applications(individual_id INTEGER,claim_id INTEGER,request_kind TEXT,status TEXT,images TEXT,image_meta TEXT);
        CREATE TABLE observations(id INTEGER,image_url TEXT,source_site TEXT);
        CREATE TABLE claim_listing_items(id INTEGER,claim_id INTEGER,field_name TEXT,value_text TEXT);
        CREATE TABLE claim_source_evidence(id INTEGER,claim_id INTEGER,evidence_type TEXT,payload_json TEXT,source_site TEXT);
        INSERT INTO individuals VALUES(1,10);
        INSERT INTO users VALUES(2,'normal','user');
        INSERT INTO claims VALUES(3,1,2,'active','positive','media',NULL,NULL,'2026-10-01','2026-10-01');
        INSERT INTO claim_evidence VALUES(3,10);
    ''')
    ref=ObjectReference('content','media/'+'a'*32,123,4,'image/jpeg')
    db.execute('INSERT INTO media_assets VALUES(10,1,?,?,?)',('image','image/jpeg',encode_reference(ref)))
    class Connection:
        def execute(self,sql,parameters=()):return db.execute(sql.replace('%s','?'),parameters)
    con=Connection();store=Mock();store.get.return_value=b'JPEG';service=CloudPublicCatalog(None,None,store)
    access=[]
    @contextmanager
    def read(actor):
        access.append(actor)
        yield con
    service._read=read
    service._guitar=Mock(return_value={'id':'1'})
    yield db,con,store,service,ref,access
    db.close()


def test_selected_public_photo_delivers_only_its_exact_storage_generation(photo_catalog):
    db,con,store,service,ref,access=photo_catalog
    assert service.photo(None,1)==b'JPEG'
    assert access==[None]
    service._guitar.assert_called_once_with(con,1)
    store.get.assert_called_once_with(ref)


@pytest.mark.parametrize('change',[
    "UPDATE individuals SET representative_media_asset_id=NULL",
    "UPDATE individuals SET representative_media_asset_id=999",
    "UPDATE media_assets SET individual_id=99",
    "UPDATE media_assets SET media_type='video'",
    "UPDATE media_assets SET mime_type='image/png'",
    "UPDATE claims SET individual_id=99",
    "UPDATE claims SET status='inactive'",
    "UPDATE claims SET verification_status='unverified'",
    "UPDATE claims SET verification_status='negative'",
    "UPDATE claims SET claim_type='ownership'",
    "UPDATE users SET ban_status='silent_ban'",
    "UPDATE users SET ban_status='ban'",
    "DELETE FROM claim_evidence",
    "UPDATE media_assets SET storage_path='/private/review-photo.jpg'",
])
def test_ineligible_or_private_photo_is_never_read_from_storage(photo_catalog,change):
    from ygc.cloud_guitars import GuitarMissing
    db,con,store,service,ref,access=photo_catalog
    db.execute(change)
    with pytest.raises(GuitarMissing):service.photo('member',1)
    store.get.assert_not_called()


def test_photo_rechecks_verification_after_previous_success(photo_catalog):
    from ygc.cloud_guitars import GuitarMissing
    db,con,store,service,ref,access=photo_catalog
    assert service.photo('member',1)==b'JPEG'
    db.execute("UPDATE claims SET verification_status='negative'")
    with pytest.raises(GuitarMissing):service.photo('member',1)
    assert store.get.call_count==1


def test_restricted_mode_blocks_photo_before_catalog_or_storage_reads(photo_catalog):
    from ygc.db.postgres_operations import ServiceRestricted
    db,con,store,service,ref,access=photo_catalog
    @contextmanager
    def restricted(actor):
        raise ServiceRestricted()
        yield
    service._read=restricted
    with pytest.raises(ServiceRestricted):service.photo(None,1)
    service._guitar.assert_not_called();store.get.assert_not_called()


def seed_listing(photo_catalog,kind='listing',state='accepted'):
    import json
    from dataclasses import replace
    from ygc.cloud_content_media import encode_reference
    db,con,store,service,ref,access=photo_catalog
    db.execute('UPDATE individuals SET representative_media_asset_id=NULL')
    db.execute("UPDATE claims SET claim_type=?,ownership_kind=?",('listing' if kind=='listing' else 'ownership',None if kind=='listing' else 'acquire'))
    closeup=replace(ref,name='media/'+'b'*32)
    db.execute('INSERT INTO acquire_applications VALUES(1,3,?,?,?,?)',(kind,state,json.dumps({'closeup':encode_reference(closeup),'overview':encode_reference(ref)}),json.dumps({'storage':'gcs-content-v1'})))
    return ref,closeup


def test_accepted_listing_uses_overview_and_never_closeup(photo_catalog):
    ref,closeup=seed_listing(photo_catalog)
    db,con,store,service,_,access=photo_catalog
    assert service.photo(None,1)==b'JPEG'
    store.get.assert_called_once_with(ref)
    assert ref!=closeup


@pytest.mark.parametrize('kind,state',[('acquire','accepted'),('listing','pending'),('listing','processing'),('listing','rejected'),('listing','cancelled')])
def test_other_application_photos_are_not_public(photo_catalog,kind,state):
    from ygc.cloud_guitars import GuitarMissing
    seed_listing(photo_catalog,kind,state)
    db,con,store,service,ref,access=photo_catalog
    with pytest.raises(GuitarMissing):service.photo(None,1)
    store.get.assert_not_called()


@pytest.mark.parametrize('change',["UPDATE claims SET verification_status='negative'", "UPDATE claims SET status='inactive'", "UPDATE users SET ban_status='silent_ban'", "UPDATE acquire_applications SET individual_id=99"])
def test_listing_publication_rechecks_claim_and_application(photo_catalog,change):
    from ygc.cloud_guitars import GuitarMissing
    seed_listing(photo_catalog)
    db,con,store,service,ref,access=photo_catalog
    db.execute(change)
    with pytest.raises(GuitarMissing):service.photo(None,1)
    store.get.assert_not_called()


@pytest.mark.parametrize('origin',['items','evidence','legacy'])
def test_crawl_uses_public_reverb_link_without_fetching_storage(photo_catalog,origin):
    import json
    from ygc.cloud_public_presentation import public_representative
    db,con,store,service,ref,access=photo_catalog
    db.execute('UPDATE individuals SET representative_media_asset_id=NULL')
    db.execute("UPDATE claims SET claim_type='listing',observation_id=7")
    url='https://rvb-img.reverb.com/image/upload/s--abc--/guitar.jpg'
    if origin=='items':
        db.executemany('INSERT INTO claim_listing_items VALUES(?,3,?,?)',[(1,'image_url',url),(2,'source_site','reverb')])
    elif origin=='evidence':
        db.execute("INSERT INTO claim_source_evidence VALUES(1,3,'marketplace_listing',?,'reverb')",(json.dumps({'provenance':{'image_url':url}}),))
    else:db.execute("INSERT INTO observations VALUES(7,?,'reverb')",(url,))
    assert public_representative(con,1)=={'remote_url':url}
    store.get.assert_not_called()


@pytest.mark.parametrize('url',['http://images.reverb.com/x','https://images.reverb.com.evil.test/x','https://user:pass@images.reverb.com/x','https://storage.googleapis.com/private/x','https://images.reverb.com:123/x','https://images.reverb.com/x#private','/api/auth/applications/private/photos/closeup','https://images.reverb.com/x\n'])
def test_reverb_image_destination_rejects_untrusted_urls(url):
    from ygc.cloud_public_presentation import reverb_image_url
    assert reverb_image_url(url) is None
