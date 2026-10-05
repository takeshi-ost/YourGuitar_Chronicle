"""Private content images linked atomically to a normal Media Claim."""
from dataclasses import asdict
from datetime import datetime,timezone
import json
from ygc.cloud_storage import ObjectReference
from ygc.cloud_avatar import normalize_image
from ygc.db.postgres import connect
from ygc.db.postgres_ownership import PostgresOwnership
from ygc.platform_boundaries import ActorContext
from ygc.cloud_guitars import positive_id,GuitarMissing

PREFIX='gcs-content-v1:'


class MediaConflict(ValueError):pass


def encode_reference(ref):
    if ref.scope!='content' or ref.content_type!='image/jpeg':raise ValueError('Invalid content image.')
    return PREFIX+json.dumps(asdict(ref),separators=(',',':'))


def decode_reference(value):
    if not isinstance(value,str) or len(value)>1024 or not value.startswith(PREFIX):raise ValueError('Unsupported content reference.')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate reference field.')
            result[key]=value
        return result
    data=json.loads(value[len(PREFIX):],object_pairs_hook=unique)
    if not isinstance(data,dict) or set(data)!={'scope','name','generation','size','content_type'}:raise ValueError('Invalid reference.')
    ref=ObjectReference(**data)
    if ref.scope!='content' or ref.content_type!='image/jpeg':raise ValueError('Invalid content image.')
    return ref


def verify_restored_media(storage,rows):
    for row in rows:
        if row['media_type']!='image' or row['mime_type']!='image/jpeg':raise ValueError('Unsupported content media.')
        storage.get(decode_reference(row['storage_path']))


class CloudContentMedia:
    def __init__(self,settings,operations,storage):self.settings,self.operations,self.storage=settings,operations,storage

    def listing(self,actor,individual,*,after=0):
        positive_id(str(individual))
        if type(after) is not int or not 0<=after<2**63:raise ValueError('Invalid page.')
        with self.operations.access('admin_read',actor):
            with connect(self.settings,'chronicle') as con:
                con.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                con.execute("SET LOCAL statement_timeout='5s'")
                if not con.execute('SELECT 1 FROM individuals WHERE id=%s',(individual,)).fetchone():raise GuitarMissing()
                total=con.execute('SELECT COUNT(*) AS n FROM media_assets WHERE individual_id=%s',(individual,)).fetchone()['n']
                rows=con.execute('''SELECT id,captured_at FROM media_assets WHERE individual_id=%s AND id>%s ORDER BY id LIMIT 26''',(individual,after)).fetchall()
                more=len(rows)>25;rows=rows[:25]
                return dict(total=str(total),items=[dict(id=str(r['id']),captured_at=r['captured_at']) for r in rows],next_after=str(rows[-1]['id']) if more else None)

    def get(self,actor,individual,media):
        positive_id(str(individual));positive_id(str(media))
        with self.operations.access('admin_read',actor):
            with connect(self.settings,'chronicle') as con:
                con.execute('SET TRANSACTION READ ONLY')
                con.execute("SET LOCAL statement_timeout='5s'")
                row=con.execute('SELECT storage_path,mime_type FROM media_assets WHERE id=%s AND individual_id=%s AND media_type=%s',(media,individual,'image')).fetchone()
                if not row:raise GuitarMissing()
                if row['mime_type']!='image/jpeg':raise ValueError('Unsupported content media.')
                return self.storage.get(decode_reference(row['storage_path']))

    def upload(self,actor,individual,data,mime):
        positive_id(str(individual))
        normalized=normalize_image(data,mime,max_side=2048)
        candidate=None;committing=False
        try:
            with connect(self.settings,'operations') as guard:
                if not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:raise MediaConflict()
                with self.operations.access('admin_write',actor) as (_,mode,account):
                    principal=ActorContext(account['id'],'identity-platform',None,True,account['app_user_id'])
                    with PostgresOwnership(self.settings)._transaction(principal,individual,require_admin=True) as (repo,canonical):
                        con=repo.connection.connection
                        timestamp=datetime.now(timezone.utc).isoformat();date=timestamp[:10]
                        verification=repo._claim_verification_status(repo.connection,canonical['id'],individual)
                        candidate=self.storage.put('content',normalized,content_type='image/jpeg')
                        claim=con.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,field_name,value_text,occurred_at,status,verification_status,created_at,updated_at)
                            VALUES(%s,%s,'media','media_type','image',%s,'active',%s,%s,%s) RETURNING id''',(individual,canonical['id'],date,verification,timestamp,timestamp)).fetchone()['id']
                        media=con.execute('''INSERT INTO media_assets(individual_id,uploader_user_id,storage_path,mime_type,captured_at,created_at,updated_at)
                            VALUES(%s,%s,%s,'image/jpeg',%s,%s,%s) RETURNING id''',(individual,canonical['id'],encode_reference(candidate),date,timestamp,timestamp)).fetchone()['id']
                        con.execute('INSERT INTO claim_evidence(claim_id,media_asset_id,created_at) VALUES(%s,%s,%s)',(claim,media,timestamp))
                        con.execute('''INSERT INTO claim_admin_actions(claim_id,individual_id,action,actor,created_at) VALUES(%s,%s,'media_create',%s,%s)''',(claim,individual,'identity-platform:'+actor,timestamp))
                        repo._rebuild_individual_snapshot_in_connection(repo.connection,individual)
                        committing=True
            return dict(claim_id=str(claim),media_id=str(media),verification_status=verification)
        except Exception:
            if candidate is not None and not committing:
                try:self.storage.delete(candidate)
                except Exception:pass
            raise
