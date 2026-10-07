"""Private Listing/Acquire intake; no review decisions or Ownership mutations."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
import secrets
import time
from ygc.acquire_review import eligibility, product_details, reference_bytes
from ygc.authentication_evidence import normalized
from ygc.claim_dates import validate_claim_date
from ygc.cloud_avatar import normalize_image
from ygc.cloud_content_media import encode_reference, decode_reference, MediaConflict
from ygc.cloud_guitars import positive_id, GuitarMissing
from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_queries import ObservationConnection
from ygc.extractors.normalization import normalize_manufacturer, normalize_serial
from ygc.listing_review import ListingInput, duplicates

IMAGE_VERSION='gcs-content-v1'
LIVE=('draft','pending','processing','error')


def revision_id(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{32}',value):raise ValueError('Invalid revision.')
    return value


def listing_input(data):
    payload=ListingInput.model_validate(data).model_dump()
    payload={key:value.strip() for key,value in payload.items()}
    serial=normalized(payload['serial_number'])
    if not normalize_manufacturer(payload['manufacturer']) or not serial or serial in ('UNKNOWN','NA','N/A','NONE','不明','未確認') or not any(c.isalnum() for c in serial):raise ValueError('Known maker and serial required.')
    validate_claim_date(payload['occurred_at'])
    return payload


def references(row):
    if not row['images']:return {}
    meta=json.loads(row['image_meta'] or '{}')
    if not isinstance(meta,dict) or meta.get('storage')!=IMAGE_VERSION:raise ValueError('Unsupported application image storage.')
    images=json.loads(row['images'])
    if not isinstance(images,dict) or set(images)-{'closeup','overview','reference'}:raise ValueError('Invalid application images.')
    for value in images.values():decode_reference(value)
    return images


def verify_restored_applications(storage,rows):
    for row in rows:
        for value in references(row).values():storage.get(decode_reference(value))
        if row['status'] in ('pending','processing','accepted') and not {'closeup','overview'}<=set(references(row)):
            raise ValueError('Submitted application photos are missing.')


def provenance(con,individual):
    """Portable provenance lookup, chosen by server rather than by applicant."""
    owner=con.execute("SELECT 1 FROM users WHERE id=%s AND account_type<>'source'",(individual['current_owner_user_id'],)).fetchone()
    candidates=con.execute('''SELECT c.* FROM claims c JOIN users u ON u.id=c.author_user_id
        WHERE c.individual_id=%s AND c.status='active' AND c.verification_status='positive' AND u.ban_status='normal'
        AND (c.claim_type='listing' OR (c.claim_type='ownership' AND c.ownership_kind='acquire'))
        ORDER BY substr(COALESCE(c.occurred_at,c.created_at),1,10) DESC,c.id DESC''',(individual['id'],)).fetchall()
    for claim in candidates:
        from ygc.claim_revision import revision
        base=dict(claim_id=claim['id'],claim_revision=revision(claim))
        if owner:
            reviewed=con.execute("SELECT * FROM acquire_applications WHERE claim_id=%s AND status='accepted'",(claim['id'],)).fetchone()
            if reviewed:
                images=references(reviewed)
                if 'overview' not in images:raise ValueError('Reference photo unavailable.')
                return base|dict(kind='stored',path=images['overview'])
            media=con.execute('''SELECT m.storage_path FROM claim_evidence e JOIN media_assets m ON m.id=e.media_asset_id
                WHERE e.claim_id=%s AND m.media_type='image' ORDER BY e.id LIMIT 1''',(claim['id'],)).fetchone()
            if media:return base|dict(kind='stored',path=media['storage_path'])
        fields={r['field_name']:r['value_text'] for r in con.execute('SELECT field_name,value_text FROM claim_listing_items WHERE claim_id=%s',(claim['id'],))}
        evidence=con.execute("SELECT source_site,payload_json FROM claim_source_evidence WHERE claim_id=%s AND evidence_type='marketplace_listing' ORDER BY id LIMIT 1",(claim['id'],)).fetchone()
        payload=json.loads(evidence['payload_json']) if evidence else {}
        source=payload.get('provenance',{}) or payload.get('source',{})
        legacy=con.execute('SELECT image_url,source_site FROM observations WHERE id=%s',(claim['observation_id'],)).fetchone() if claim['observation_id'] else None
        url=fields.get('image_url') or source.get('image_url') or (legacy['image_url'] if legacy else None)
        site=(evidence['source_site'] if evidence else None) or fields.get('source_site') or (legacy['source_site'] if legacy else None)
        if url and site=='reverb':return base|dict(kind='reverb',url=url)
        if owner:return base|dict(kind='absent')
    return dict(kind='absent')


class CloudApplications:
    def __init__(self,settings,operations,storage):self.settings,self.operations,self.storage=settings,operations,storage

    @contextmanager
    def transaction(self,actor,write=False):
        with connect(self.settings,'operations') as guard:
            if write and not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:raise MediaConflict()
            with self.operations.access('user_write' if write else 'user_read',actor) as (_,mode,account):
                with PostgresAccounts(self.settings).content_transaction(actor,(account['id'],)) as (con,canonical):
                    con.execute("SET LOCAL statement_timeout='5s'")
                    con.execute("SET LOCAL lock_timeout='2s'")
                    yield con,canonical['id'],mode

    @staticmethod
    def detail(row):
        status='expired' if row['status']=='draft' and row['expires_at']<=time.time() else row['status']
        result=json.loads(row['result']) if row.get('result') else {}
        admin_review=None
        if row.get('admin_decision_note'):
            decision=json.loads(row['admin_decision_note'])
            if decision.get('operation') in ('accept','reject'):
                admin_review={key:decision.get(key) for key in ('operation','reason')}
                admin_review['at']=row.get('admin_decision_at')
        return dict(revision=row['revision'],kind=row['request_kind'],individual_id=str(row['individual_id']) if row['individual_id'] else None,
            serial=row['serial'],challenge=row['challenge'],expires_at=row['expires_at'],status=status,
            payload=json.loads(row['listing_payload']) if row['listing_payload'] else None,
            acquisition_date=row['acquisition_date'],body=row['body'] or '',photos=[role for role in references(row) if role!='reference'],
            claim_id=str(row['claim_id']) if row.get('claim_id') else None,
            verification_status=row.get('claim_verification'),
            reasons=result.get('adjudication',{}).get('reasons',[]),admin_review=admin_review)

    @staticmethod
    def find(con,user,revision):
        revision_id(revision)
        row=con.execute('''SELECT *,
            (SELECT note FROM acquire_application_events e WHERE e.revision=acquire_applications.revision AND e.kind IN ('admin_accept','admin_reject','admin_retry') ORDER BY e.id DESC LIMIT 1) AS admin_decision_note,
            (SELECT at FROM acquire_application_events e WHERE e.revision=acquire_applications.revision AND e.kind IN ('admin_accept','admin_reject','admin_retry') ORDER BY e.id DESC LIMIT 1) AS admin_decision_at
            FROM acquire_applications WHERE revision=%s AND applicant_id=%s FOR UPDATE''',(revision,user)).fetchone()
        if not row:raise GuitarMissing()
        return row

    @staticmethod
    def event(con,revision,kind):
        con.execute('INSERT INTO acquire_application_events(revision,at,kind) VALUES(%s,%s,%s)',(revision,datetime.now(timezone.utc).isoformat(),kind))

    def list(self,actor):
        with self.transaction(actor) as (con,user,mode):
            rows=con.execute('''SELECT *, (SELECT verification_status FROM claims WHERE id=acquire_applications.claim_id) AS claim_verification,
                (SELECT note FROM acquire_application_events e WHERE e.revision=acquire_applications.revision AND e.kind IN ('admin_accept','admin_reject','admin_retry') ORDER BY e.id DESC LIMIT 1) AS admin_decision_note,
                (SELECT at FROM acquire_application_events e WHERE e.revision=acquire_applications.revision AND e.kind IN ('admin_accept','admin_reject','admin_retry') ORDER BY e.id DESC LIMIT 1) AS admin_decision_at
                FROM acquire_applications WHERE applicant_id=%s
                ORDER BY CASE WHEN status IN ('pending','processing','error') OR (status='draft' AND expires_at>%s) THEN 0 ELSE 1 END,
                created_at DESC,revision DESC LIMIT 50''',(user,time.time())).fetchall()
            # user_read already fences admin_only to a canonical Admin; even
            # an Admin acting as an applicant cannot write during read_only.
            return dict(items=[self.detail(row) for row in rows],can_write=mode['mode'] in ('normal','admin_only'))

    def start(self,actor,data):
        if not isinstance(data,dict) or set(data)-{'kind','payload','individual_id'}:raise ValueError('Invalid application.')
        kind=data.get('kind')
        payload=listing_input(data.get('payload')) if kind=='listing' else None
        individual=positive_id(data.get('individual_id')) if kind=='acquire' else None
        if kind not in ('listing','acquire') or (kind=='listing' and 'individual_id' in data) or (kind=='acquire' and 'payload' in data):raise ValueError('Invalid application kind.')
        with self.transaction(actor,True) as (con,user,_):
            shared=ObservationConnection(con)
            if kind=='listing':
                ids=duplicates(shared,payload)
                if ids:return dict(status='duplicate',existing_individual_ids=[str(i) for i in ids])
                serial=payload['serial_number'];details=dict(maker=payload['manufacturer'],model=payload['model'] or None,finish=payload['finish'] or None)
            else:
                target=eligibility(shared,user,individual)
                from ygc.disputes import guard
                guard(shared,individual)
                serial=target['serial_number'];details=None
                waiting=con.execute('''SELECT a.* FROM acquire_applications a JOIN claims c ON c.id=a.claim_id
                    WHERE a.applicant_id=%s AND c.individual_id=%s AND a.status='accepted'
                    AND c.status='active' AND c.verification_status='unverified' LIMIT 1''',(user,individual)).fetchone()
                if waiting:return self.detail(waiting)
            for row in con.execute('SELECT * FROM acquire_applications WHERE applicant_id=%s AND request_kind=%s AND status=ANY(%s)',(user,kind,list(LIVE))):
                if row['status']=='draft' and row['expires_at']<=time.time():
                    # Expiry is a write-time transition. Releasing the active
                    # unique slot lets a new Acquire get a fresh Challenge.
                    con.execute("UPDATE acquire_applications SET status='expired' WHERE revision=%s",(row['revision'],))
                    self.event(con,row['revision'],'expired')
                    continue
                matches=row['individual_id']==individual if kind=='acquire' else normalize_manufacturer(json.loads(row['listing_payload'])['manufacturer'])==normalize_manufacturer(payload['manufacturer']) and normalize_serial(row['serial'])==normalize_serial(serial)
                if matches:return self.detail(row)
            count=con.execute('SELECT COUNT(*) AS n FROM acquire_applications WHERE applicant_id=%s AND status=ANY(%s) AND (status<>%s OR expires_at>%s)',(user,list(LIVE),'draft',time.time())).fetchone()['n']
            if count>=25:raise ValueError('Too many active applications.')
            revision=secrets.token_hex(16);challenge=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
            con.execute('''INSERT INTO acquire_applications(revision,request_kind,listing_payload,applicant_id,individual_id,original_individual_id,
                serial,challenge,expires_at,created_at,prompt_version,product_details,acquisition_date,body,image_meta)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (revision,kind,json.dumps(payload) if payload else None,user,individual,individual or 0,serial,challenge,time.time()+86400,
                 datetime.now(timezone.utc).isoformat(),kind+'-evidence-v1',json.dumps(details) if details else None,
                 payload['occurred_at'] if payload else None,payload['body'] if payload else '',json.dumps(dict(storage=IMAGE_VERSION))))
            self.event(con,revision,'created')
            return self.detail(self.find(con,user,revision))

    @staticmethod
    def draft(row):
        if row['status']!='draft' or row['expires_at']<=time.time():raise ValueError('Application is not an unexpired draft.')

    def upload(self,actor,revision,role,data,mime):
        revision_id(revision)
        if role not in ('closeup','overview'):raise ValueError('Invalid photo role.')
        image=normalize_image(data,mime,max_side=2048);candidate=None;committing=False
        try:
            with self.transaction(actor,True) as (con,user,_):
                row=self.find(con,user,revision);self.draft(row)
                images=references(row);candidate=self.storage.put('content',image,content_type='image/jpeg')
                images[role]=encode_reference(candidate)
                con.execute('UPDATE acquire_applications SET images=%s WHERE revision=%s',(json.dumps(images),revision))
                self.event(con,revision,'photo_'+role);result=self.detail(row|{'images':json.dumps(images)});committing=True
            return result
        except Exception:
            if candidate is not None and not committing:
                try:self.storage.delete(candidate)
                except Exception:pass
            raise

    def image(self,actor,revision,role):
        if role not in ('closeup','overview'):raise ValueError('Invalid photo role.')
        with self.transaction(actor) as (con,user,_):
            row=self.find(con,user,revision);path=references(row).get(role)
            if not path:raise GuitarMissing()
            return self.storage.get(decode_reference(path))

    def cancel(self,actor,revision):
        with self.transaction(actor,True) as (con,user,_):
            row=self.find(con,user,revision)
            if row['status'] in ('draft','pending','processing','error'):
                con.execute("UPDATE acquire_applications SET status='cancelled',completed_at=%s,lease_token=NULL,lease_until=NULL WHERE revision=%s",(datetime.now(timezone.utc).isoformat(),revision))
                self.event(con,revision,'cancelled');row=row|{'status':'cancelled'}
            elif row['status']!='cancelled':raise ValueError('Application is already decided.')
            return self.detail(row)

    def retry(self,actor,revision):
        with self.transaction(actor,True) as (con,user,_):
            row=self.find(con,user,revision)
            if row['status']=='pending':return self.detail(row)
            if row['status']!='error' or row['claim_id']:raise ValueError('Only failed applications can be retried.')
            con.execute("UPDATE acquire_applications SET status='pending',completed_at=NULL,received=NULL,result=NULL,report=NULL,error=NULL,attempts=0,lease_token=NULL,lease_until=NULL,product_observations=NULL WHERE revision=%s",(revision,))
            self.event(con,revision,'retry')
            return self.detail(self.find(con,user,revision))

    def submit(self,actor,revision,data):
        if not isinstance(data,dict) or set(data)-{'acquisition_date','body'}:raise ValueError('Invalid submission.')
        date=data.get('acquisition_date');body=data.get('body','')
        if not isinstance(date,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) or not isinstance(body,str) or len(body)>4000:raise ValueError('Invalid acquisition date or explanation.')
        validate_claim_date(date)
        candidate=None;committing=False
        try:
            with self.transaction(actor,True) as (con,user,_):
                row=self.find(con,user,revision)
                if row['status']=='pending':
                    if row['acquisition_date']!=date or row['body']!=body:raise ValueError('Submission already recorded with different details.')
                    return self.detail(row)
                self.draft(row);images=references(row)
                if not {'closeup','overview'}<=set(images):raise ValueError('Both photos are required.')
                for value in images.values():self.storage.get(decode_reference(value))
                shared=ObservationConnection(con)
                if row['request_kind']=='listing':
                    payload=json.loads(row['listing_payload'])
                    if duplicates(shared,payload):raise ValueError('Maker and serial already registered.')
                    if date!=payload['occurred_at'] or body!=payload['body']:raise ValueError('Listing details cannot change at submission.')
                    source={'kind':'absent'};details=json.loads(row['product_details'])
                else:
                    target=eligibility(shared,user,row['individual_id'])
                    from ygc.disputes import guard
                    guard(shared,target['id'])
                    if normalized(target['serial_number'])!=normalized(row['serial']):raise ValueError('Registered serial changed.')
                    details=product_details(shared,target);source=provenance(con,target)
                    if source['kind']=='stored':
                        self.storage.get(decode_reference(source['path']));images['reference']=source['path']
                    elif source['kind']=='reverb':
                        # Approved Reverb host, bounded download, no redirect or user URL.
                        raw=reference_bytes(source,None)
                        from PIL import Image
                        from io import BytesIO
                        with Image.open(BytesIO(raw)) as image:mime=Image.MIME.get(image.format)
                        photo=normalize_image(raw,mime,max_side=2048)
                        candidate=self.storage.put('content',photo,content_type='image/jpeg');images['reference']=encode_reference(candidate)
                con.execute('''UPDATE acquire_applications SET status='pending',images=%s,reference_source=%s,product_details=%s,
                    acquisition_date=%s,body=%s,submitted_at=%s WHERE revision=%s''',(json.dumps(images),json.dumps(source),json.dumps(details),date,body,datetime.now(timezone.utc).isoformat(),revision))
                self.event(con,revision,'submitted');result=self.detail(self.find(con,user,revision));committing=True
            return result
        except Exception:
            if candidate is not None and not committing:
                try:self.storage.delete(candidate)
                except Exception:pass
            raise
