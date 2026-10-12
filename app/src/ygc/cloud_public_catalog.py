"""Public-only, bounded Chronicle projections. Never reads application/photo data.

This projection is deliberately smaller than the local prototype and Admin API.
Public display fields are explicitly projected; Evidence and storage references
remain private. Service-mode locks fence each read against maintenance changes.
"""
from contextlib import contextmanager
import re
from urllib.parse import urlsplit

from ygc.cloud_guitars import GuitarMissing, MAX_ID, positive_id
from ygc.db.postgres import connect
from ygc.cloud_public_presentation import public_people, enrich_claims, claim_presentation, public_representative, reverb_image_url

GUITAR_FIELDS = ('manufacturer', 'model', 'finish', 'year', 'serial_number')
SPEC_FIELDS = ('body', 'bridge', 'fingerboard', 'frets', 'neck', 'nut',
               'pickups', 'pickguard', 'potentiometers', 'tuners', 'wiring', 'weight', 'finish')
CLAIM_TYPES = ('listing', 'ownership', 'identity_correction', 'specification',
               'repair', 'incident', 'event', 'media')
STATES = ('positive', 'unverified', 'negative')
OWNERSHIP_KINDS = ('acquire', 'release', 'transfer', 'lost', 'inherit')
SORTS = {'newest': 'i.id DESC', 'oldest': 'i.id ASC',
         'maker': 'lower(i.manufacturer) ASC NULLS LAST, lower(i.model) ASC NULLS LAST, i.id ASC',
         'model': 'lower(i.model) ASC NULLS LAST, lower(i.manufacturer) ASC NULLS LAST, i.id ASC'}
# Formal table headings use the local lowercase text comparison and ID tie-break.
SORTS.update({field + '_' + direction: "COALESCE(lower(i." + field + "), '') COLLATE \"C\" " + direction.upper() + ', i.id ASC'
              for field in GUITAR_FIELDS for direction in ('asc', 'desc')})
MAX_PAGE = 1000000
VISIBLE_CLAIM = "c.status='active' AND u.ban_status='normal' AND c.claim_type=ANY(%s) AND c.verification_status=ANY(%s)"
VISIBLE_GUITAR = f'EXISTS (SELECT 1 FROM claims c JOIN users u ON u.id=c.author_user_id WHERE c.individual_id=i.id AND {VISIBLE_CLAIM})'
# Count only the same active, visible Claim types/states exposed by Chronicle.
PUBLIC_CLAIM_COUNT = "(SELECT CAST(COUNT(*) AS TEXT) FROM claims counted JOIN users author ON author.id=counted.author_user_id WHERE counted.individual_id=i.id AND counted.status='active' AND author.ban_status='normal' AND counted.claim_type IN (" + ','.join(repr(v) for v in CLAIM_TYPES) + ") AND counted.verification_status IN (" + ','.join(repr(v) for v in STATES) + ")) AS claim_count"
COLUMNS = PUBLIC_CLAIM_COUNT + ',i.id,' + ','.join('left(i.' + field + ',200) AS ' + field for field in GUITAR_FIELDS)


def parameters(query):
    if set(query)-{'q', 'sort', 'page', 'limit'} or any(len(query.getlist(k)) != 1 for k in query):
        raise ValueError('Unknown or repeated query parameter.')
    q = query.get('q', '')
    sort = query.get('sort', 'newest')
    page = positive_id(query['page']) if 'page' in query else 1
    limit = positive_id(query['limit']) if 'limit' in query else 24
    validate_page(q, sort, page, limit)
    return q.strip(), sort, page, limit


def validate_page(q, sort, page, limit):
    if (not isinstance(q, str) or len(q) > 120 or any(ord(c) < 32 or ord(c) == 127 for c in q)
            or not isinstance(sort, str) or sort not in SORTS
            or type(page) is not int or not 1 <= page <= MAX_PAGE
            or type(limit) is not int or not 1 <= limit <= 50):
        raise ValueError('Invalid catalog page.')


def identifier(value):
    if type(value) is not int or not 0 < value <= MAX_ID:
        raise ValueError('Invalid identifier.')


def guitar_projection(row):
    # Defense in depth: service and HTTP boundary both use this allowlist.
    result = {'id': str(row['id']), **{key: row.get(key) for key in GUITAR_FIELDS}, 'photo': None}
    if 'claim_count' in row:
        count = str(row['claim_count'])
        if not re.fullmatch(r'0|[1-9][0-9]{0,18}', count) or int(count) > MAX_ID:
            raise ValueError('Invalid Claim count.')
        result['claim_count'] = count
    return result


def public_source_url(site, listing_id, value):
    """Only a canonical public marketplace item, never arbitrary evidence URLs.

    Query strings, fragments, credentials, storage hosts and URL shorteners are
    rejected rather than sent to the browser. No remote requests are made.
    """
    if site != 'reverb' or not isinstance(listing_id, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', listing_id):
        return None
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or url.netloc not in ('reverb.com', 'www.reverb.com')
                or url.query or url.fragment
                or not re.fullmatch(r'/item/' + re.escape(listing_id) + r'(?:-[A-Za-z0-9_-]+)?/?', url.path)):
            return None
    except ValueError:
        return None
    return 'https://reverb.com/item/' + listing_id


def claim_projection(row):
    state = row['verification_status']
    positive = state == 'positive'
    source = row.get('source_url')
    result = {'id': str(row['id']), 'claim_type': row['claim_type'],
            'ownership_kind': row.get('ownership_kind') if row.get('ownership_kind') in OWNERSHIP_KINDS else None,
            'occurred_at': row.get('occurred_at'), 'created_at': row.get('created_at'),
            'verification_status': state,
            'items': [{'field_name': item['field_name'], 'value_text': item['value_text']}
                      for item in row.get('items', []) if item['field_name'] in (*GUITAR_FIELDS, *SPEC_FIELDS)] if positive else [],
            'source_url': source if positive and isinstance(source, str)
                          and re.fullmatch(r'https://reverb\.com/item/[1-9][0-9]{0,19}', source) else None}
    if 'presentation' in row:
        result['presentation'] = claim_presentation(row['presentation'])
    return result


class CloudPublicCatalog:
    def __init__(self, settings, operations, storage=None):
        self.settings, self.operations, self.storage = settings, operations, storage

    def discoveries(self, actor=None):
        from ygc.cloud_catalog_insights import discoveries
        return discoveries(self, actor)

    def statistics(self, actor=None):
        from ygc.cloud_catalog_insights import statistics
        return statistics(self, actor)

    def world_map(self, actor=None):
        from ygc.cloud_catalog_insights import world_map
        return world_map(self, actor)

    @contextmanager
    def _read(self, actor):
        # public_read deliberately has no Admin bypass for Offline. Admin-only
        # accepts only a canonically active Admin resolved by the API verifier.
        with self.operations.access('public_read', actor):
            with connect(self.settings, 'chronicle') as con:
                con.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                con.execute("SET LOCAL statement_timeout='5s'")
                con.execute("SET LOCAL lock_timeout='2s'")
                yield con

    @staticmethod
    def _guitar(con, individual_id):
        row = con.execute(f'SELECT {COLUMNS} FROM individuals i WHERE i.id=%s AND {VISIBLE_GUITAR}',
                          (individual_id, list(CLAIM_TYPES), list(STATES))).fetchone()
        if row is None:
            raise GuitarMissing()
        return guitar_projection(row)

    def list(self, actor=None, *, q='', sort='newest', page=1, limit=24):
        validate_page(q, sort, page, limit)
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        where = f"{VISIBLE_GUITAR} AND concat_ws(' ', i.manufacturer, i.model, i.finish, i.year, i.serial_number) ILIKE %s"
        args = (list(CLAIM_TYPES), list(STATES), pattern)
        with self._read(actor) as con:
            total = con.execute(f'SELECT COUNT(*) AS total FROM individuals i WHERE {where}', args).fetchone()['total']
            rows = con.execute(f'SELECT {COLUMNS} FROM individuals i WHERE {where} ORDER BY {SORTS[sort]} LIMIT %s OFFSET %s',
                               (*args, limit, (page-1)*limit)).fetchall()
            return {'items': [guitar_projection(row) for row in rows], 'total': str(total),
                    'page': page, 'page_size': limit, 'total_pages': (total+limit-1)//limit}

    def detail(self, actor, individual_id):
        identifier(individual_id)
        with self._read(actor) as con:
            result = self._guitar(con, individual_id)
            # Match the prototype's event-day / Claim-ID ordering and its
            # supported legacy single-field specifications. Custom labels do
            # not constitute a public-field declaration. Never select c.body.
            rows = con.execute('''WITH permitted AS (
                SELECT c.id,c.field_name,c.value_text,c.occurred_at,c.created_at
                FROM claims c JOIN users u ON u.id=c.author_user_id
                WHERE c.individual_id=%s AND c.claim_type='specification' AND c.status='active'
                  AND c.verification_status='positive' AND u.ban_status='normal'),
                candidates AS (
                  SELECT c.id AS claim_id,c.field_name,left(c.value_text,1000) AS value_text,
                    c.occurred_at,c.created_at,0 AS item_id FROM permitted c WHERE c.field_name=ANY(%s) AND c.value_text IS NOT NULL
                  UNION ALL
                  SELECT c.id,s.field_name,left(s.value_text,1000),c.occurred_at,c.created_at,s.id
                    FROM claim_spec_items s JOIN permitted c ON c.id=s.claim_id WHERE s.field_name=ANY(%s))
                SELECT DISTINCT ON (field_name) field_name,value_text FROM candidates
                ORDER BY field_name,left(COALESCE(occurred_at,created_at),10) DESC,claim_id DESC,item_id DESC''',
                (individual_id, list(SPEC_FIELDS), list(SPEC_FIELDS))).fetchall()
            result['specifications'] = [dict(row) for row in rows]
            owner = con.execute('SELECT current_owner_user_id,current_owner_name FROM individuals WHERE id=%s', (individual_id,)).fetchone()
            person = public_people(self.settings, [owner['current_owner_user_id']]).get(owner['current_owner_user_id'], {})
            photo = public_representative(con, individual_id)
            supported_photo = False
            remote_photo = reverb_image_url(photo.get('remote_url')) if photo else None
            if photo and not remote_photo:
                from ygc.cloud_content_media import decode_reference
                try:
                    decode_reference(photo['storage_path'])
                    supported_photo = True
                except (ValueError, TypeError, KeyError):
                    pass
            result['public_photo'] = '/api/public/guitars/'+str(individual_id)+'/photo' if supported_photo else remote_photo
            result['presentation'] = {'owner': person.get('person'), 'location': person.get('location'),
                'source_owner_name': owner['current_owner_name'][:200] if owner['current_owner_user_id'] is None and owner['current_owner_name'] else None}
            return result

    def photo(self, actor, individual_id):
        identifier(individual_id)
        from ygc.cloud_content_media import decode_reference
        with self._read(actor) as con:
            self._guitar(con, individual_id)
            row = public_representative(con, individual_id)
            if not row or row.get('remote_url'):
                raise GuitarMissing()
            try:
                reference = decode_reference(row['storage_path'])
            except (ValueError, TypeError, KeyError):
                raise GuitarMissing() from None
            if self.storage is None:
                raise RuntimeError('Content storage unavailable.')
            return self.storage.get(reference)

    def chronicle(self, actor, individual_id, *, after=0, limit=25):
        identifier(individual_id)
        if type(after) is not int or not 0 <= after <= MAX_ID or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Invalid Chronicle page.')
        with self._read(actor) as con:
            self._guitar(con, individual_id)
            rows = con.execute(f'''SELECT c.id,c.author_user_id,left(c.body,8000) AS body,c.claim_type,c.ownership_kind,left(c.occurred_at,40) AS occurred_at,
                left(c.created_at,40) AS created_at,c.verification_status FROM claims c JOIN users u ON u.id=c.author_user_id
                WHERE c.individual_id=%s AND {VISIBLE_CLAIM} AND (%s=0 OR c.id<%s)
                ORDER BY c.id DESC LIMIT %s''',
                (individual_id, list(CLAIM_TYPES), list(STATES), after, after, limit+1)).fetchall()
            more = len(rows) > limit
            rows = [dict(row, items=[], source_url=None) for row in rows[:limit]]
            positive = {row['id']: row for row in rows if row['verification_status'] == 'positive'}
            if positive:
                ids = list(positive)
                # Read only fixed public guitar fields, never owner/location,
                # free-form Claim body, diagnostics or any media reference.
                for table, kind, fields in [('claim_listing_items', 'listing', GUITAR_FIELDS),
                                            ('claim_spec_items', 'specification', SPEC_FIELDS)]:
                    items = con.execute(f'''SELECT claim_id,field_name,value_text FROM
                        (SELECT s.claim_id,s.field_name,left(s.value_text,1000) AS value_text,
                          row_number() OVER(PARTITION BY s.claim_id,s.field_name ORDER BY s.id DESC) AS n
                         FROM {table} s JOIN claims c ON c.id=s.claim_id
                         WHERE s.claim_id=ANY(%s) AND c.claim_type=%s AND s.field_name=ANY(%s)) bounded
                        WHERE n=1 ORDER BY claim_id,field_name''', (ids, kind, list(fields))).fetchall()
                    for item in items:
                        positive[item['claim_id']]['items'].append({'field_name': item['field_name'], 'value_text': item['value_text']})
                legacy_specs = con.execute('''SELECT id AS claim_id,field_name,left(value_text,1000) AS value_text
                    FROM claims WHERE id=ANY(%s) AND claim_type='specification' AND field_name=ANY(%s) AND value_text IS NOT NULL''',
                    (ids, list(SPEC_FIELDS))).fetchall()
                for item in legacy_specs:
                    existing = positive[item['claim_id']]['items']
                    if not any(row['field_name'] == item['field_name'] for row in existing):
                        existing.append({'field_name': item['field_name'], 'value_text': item['value_text']})
                # Public marketplace provenance has its own allowlist. An
                # acquisition-date Evidence or review Evidence is never read.
                sources = con.execute('''SELECT claim_id,source_site,source_listing_id,source_url FROM
                    (SELECT e.claim_id,e.source_site,e.source_listing_id,left(e.source_url,2049) AS source_url,
                      row_number() OVER(PARTITION BY e.claim_id ORDER BY e.id) AS n
                     FROM claim_source_evidence e JOIN claims c ON c.id=e.claim_id
                     WHERE e.claim_id=ANY(%s) AND e.evidence_type='marketplace_listing'
                       AND (c.claim_type='listing' OR (c.claim_type='ownership' AND c.ownership_source='automation')))
                    bounded WHERE n=1 ORDER BY claim_id''', (ids,)).fetchall()
                for source in sources:
                    positive[source['claim_id']]['source_url'] = public_source_url(
                        source['source_site'], source['source_listing_id'], source['source_url'])
            enrich_claims(self.settings, con, rows)
            return {'items': [claim_projection(row) for row in rows],
                    'next_after': str(rows[-1]['id']) if more else None}
