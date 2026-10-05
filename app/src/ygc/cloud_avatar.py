"""Self-only account avatars. Stored objects remain private and generation-qualified."""
from dataclasses import asdict
from datetime import datetime, timezone
from io import BytesIO
import json
import threading
import uuid
from PIL import Image, ImageOps, UnidentifiedImageError
from ygc.cloud_storage import ObjectReference

MAX_UPLOAD = 8 * 1024 * 1024
MAX_PIXELS = 8_000_000
NORMALIZING = threading.BoundedSemaphore(1)
PREFIX = 'gcs-avatar-v1:'


class AvatarMissing(LookupError):
    pass


def encode_reference(ref):
    if ref.scope != 'accounts' or ref.content_type != 'image/jpeg':
        raise ValueError('Invalid avatar reference.')
    return PREFIX + json.dumps(asdict(ref), separators=(',', ':'))


def decode_reference(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        raise ValueError('Unsupported avatar reference.')
    data = json.loads(value[len(PREFIX):])
    if not isinstance(data, dict) or set(data) != {'scope','name','generation','size','content_type'}:
        raise ValueError('Invalid avatar reference.')
    ref = ObjectReference(**data)
    if ref.scope != 'accounts' or ref.content_type != 'image/jpeg':
        raise ValueError('Invalid avatar reference.')
    return ref


class ImageUploadInvalid(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__('Invalid image upload.')


def normalize_image(data, content_type, *, max_side=512):
    if max_side not in (512,2048):raise ValueError('Invalid image dimensions.')
    formats = {'image/jpeg':'JPEG','image/png':'PNG','image/webp':'WEBP'}
    if content_type not in formats:raise ImageUploadInvalid('image_format')
    if not isinstance(data,bytes) or not data:raise ImageUploadInvalid('invalid_image')
    if len(data)>MAX_UPLOAD:raise ImageUploadInvalid('image_size_limit')
    with NORMALIZING:
        try:
            with Image.open(BytesIO(data)) as image:
                if image.format!=formats[content_type] or getattr(image,'n_frames',1)!=1:raise ImageUploadInvalid('image_format')
                if image.width*image.height>MAX_PIXELS:raise ImageUploadInvalid('image_pixel_limit')
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                try:
                    oriented.thumbnail((max_side,max_side))
                    rgba = oriented.convert('RGBA')
                    canvas = Image.new('RGB',rgba.size,'white')
                    try:
                        canvas.paste(rgba,mask=rgba.getchannel('A'))
                        output=BytesIO();canvas.save(output,format='JPEG',quality=85)
                        return output.getvalue()
                    finally:
                        canvas.close();rgba.close()
                finally:
                    if oriented is not image:oriented.close()
        except Image.DecompressionBombError:raise ImageUploadInvalid('image_pixel_limit') from None
        except (UnidentifiedImageError,OSError,SyntaxError,OverflowError):
            raise ImageUploadInvalid('invalid_image') from None


class CloudAvatar:
    def __init__(self, operations, storage):
        self.operations, self.storage = operations, storage

    def get(self, actor, *, admin=False):
        with self.operations.account_access('admin_read' if admin else 'user_read', actor) as (con, mode, account):
            value = account['avatar_storage_path']
            if not value:
                raise AvatarMissing()
            return self.storage.get(decode_reference(value))

    def set(self, actor, data=None, content_type=None, *, admin=False):
        # Normalize before holding DB locks; no remote write occurs before authorization.
        normalized = normalize_image(data, content_type) if data is not None else None
        candidate = None
        committing = False
        try:
            with self.operations.account_access('admin_write' if admin else 'user_write', actor) as (con, mode, account):
                previous = account['avatar_storage_path']
                if previous:
                    decode_reference(previous)
                if normalized is not None:
                    candidate = self.storage.put('accounts', normalized, content_type='image/jpeg')
                value = encode_reference(candidate) if candidate else None
                timestamp = datetime.now(timezone.utc).isoformat()
                con.execute('''UPDATE account_records SET avatar_storage_path=%s,avatar_mime_type=%s,
                    avatar_original_filename=NULL,updated_at=%s WHERE app_user_id=%s''',
                    (value,'image/jpeg' if value else None,timestamp,actor))
                con.execute('INSERT INTO account_metadata(key,value) VALUES(%s,%s)',
                    ('avatar:'+str(uuid.uuid4()),json.dumps({'action':'avatar_set' if value else 'avatar_remove',
                     'actor_app_user_id':actor,'occurred_at':timestamp,'administrative_path':admin})))
                committing = True
            return {'has_avatar':value is not None}
        except Exception:
            # Before commit starts, the Accounts context rolled back. An ambiguous
            # commit failure retains the candidate so a committed reference cannot break.
            if candidate is not None and not committing:
                try:self.storage.delete(candidate)
                except Exception:pass
            raise
        # Previous images are retained for independent Accounts backup/restore.
