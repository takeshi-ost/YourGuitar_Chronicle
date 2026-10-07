"""Private, Claim-bound Media/Event attachment projection and revision material.

Storage references never cross the HTTP boundary. Each image must belong to
this Claim's author and guitar and must not also be evidence for another Claim.
No application/proof-photo lookup or caller-supplied object reference exists.
"""
from ygc.cloud_content_media import decode_reference
from ygc.cloud_guitars import GuitarMissing

PHOTO_CLAIM_TYPES = ('media', 'event')
MAX_IMAGES = 10
MAX_TOTAL_UPLOAD = 24 * 1024 * 1024


def media_rows(connection, claim):
    if claim['claim_type'] not in PHOTO_CLAIM_TYPES:
        return []
    rows = connection.execute('''SELECT e.id AS evidence_id,
        e.created_at AS evidence_created_at,m.id,m.individual_id,m.uploader_user_id,
        m.media_type,m.storage_path,m.mime_type,m.captured_at,m.created_at,m.updated_at,
        EXISTS (SELECT 1 FROM claim_evidence other
            WHERE other.media_asset_id=e.media_asset_id AND other.claim_id<>e.claim_id) AS shared
        FROM claim_evidence e LEFT JOIN media_assets m ON m.id=e.media_asset_id
        WHERE e.claim_id=? ORDER BY e.id LIMIT 11''', (claim['id'],)).fetchall()
    if (not rows and claim['claim_type'] == 'media') or len(rows) > MAX_IMAGES:
        raise GuitarMissing()
    for row in rows:
        if (row['id'] is None or row['individual_id'] != claim['individual_id']
                or row['uploader_user_id'] != claim['author_user_id'] or row['shared']
                or row['media_type'] != 'image'):
            raise GuitarMissing()
    return [dict(row) for row in rows]


def media_projection(connection, claim):
    if claim['claim_type'] not in PHOTO_CLAIM_TYPES:
        return {}
    # The storage reference is validated on delivery, so legacy local images
    # remain manageable without ever exposing their old path or filename.
    return {'media_items': [{'id': str(row['id']), 'mime_type': 'image/jpeg'}
                            for row in media_rows(connection, claim)]}


def image_reference(row):
    if row['mime_type'] != 'image/jpeg':
        raise ValueError('Unsupported content media.')
    return decode_reference(row['storage_path'])
