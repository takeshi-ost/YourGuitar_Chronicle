"""Explicit public display fields; never project Evidence or storage references."""
from ygc.db.postgres import connect


def person_projection(value):
    if not isinstance(value, dict):
        return None
    key = str(value.get('id', ''))
    name = value.get('display_name')
    if not key.isascii() or not key.isdigit() or not 0 < int(key) < 2**63 or not isinstance(name, str):
        return None
    return {'id': key, 'display_name': name[:120]}


def claim_presentation(value):
    if not isinstance(value, dict):
        return None
    body = value.get('body')
    counts = {}
    for key in ('good_count', 'bad_count'):
        raw = str(value.get(key, '0'))
        counts[key] = raw if raw.isascii() and raw.isdigit() and 0 <= int(raw) < 2**63 else '0'
    return {'author': person_projection(value.get('author')),
            'body': body[:8000] if isinstance(body, str) else None, **counts}


def public_people(settings, ids):
    """Canonical Accounts, not a stale Chronicle profile replica.

    This is the anonymous public projection: Members/Followers/Private locations
    are omitted even if an authenticated caller uses this public endpoint.
    """
    ids = list({int(key) for key in ids if key is not None})
    if not ids:
        return {}
    with connect(settings, 'accounts') as con:
        con.execute('SET TRANSACTION READ ONLY')
        con.execute("SET LOCAL statement_timeout='5s'")
        rows = con.execute('''SELECT id,display_name,account_type,location_country,location_region,residence_visibility
            FROM account_records WHERE id=ANY(%s) AND disabled=0 AND ban_status='normal' ''', (ids,)).fetchall()
        return {row['id']: {'person': person_projection(dict(row)),
                'location': ' / '.join(filter(None, [row['location_country'], row['location_region']]))[:400]
                if row['residence_visibility'] == 'Public' else None} for row in rows}


def enrich_claims(settings, con, rows):
    if not rows:
        return
    people = public_people(settings, [row['author_user_id'] for row in rows])
    counts = con.execute('''SELECT v.claim_id,
        COUNT(*) FILTER (WHERE v.vote='good') AS good_count,
        COUNT(*) FILTER (WHERE v.vote='bad') AS bad_count
        FROM claim_votes v JOIN users u ON u.id=v.user_id
        WHERE v.claim_id=ANY(%s) AND u.ban_status='normal' GROUP BY v.claim_id''',
        ([row['id'] for row in rows],)).fetchall()
    by_id = {row['claim_id']: row for row in counts}
    for row in rows:
        row['presentation'] = claim_presentation({'author': people.get(row['author_user_id'], {}).get('person'),
            # Identity correction reasons belong to the author's private
            # correction history, even though the Claim itself is public.
            'body': None if row.get('claim_type') == 'identity_correction' else row.get('body'),
            **{key: by_id.get(row['id'], {}).get(key, 0) for key in ('good_count', 'bad_count')}})


def representative(con, individual_id):
    """Only an explicitly selected, positive public Listing/Media image.

    Acquire review photos live elsewhere and are deliberately never considered.
    """
    return con.execute('''SELECT m.storage_path,m.mime_type FROM individuals i
        JOIN media_assets m ON m.id=i.representative_media_asset_id AND m.individual_id=i.id
        WHERE i.id=%s AND m.media_type='image' AND m.mime_type='image/jpeg'
        AND EXISTS (SELECT 1 FROM claim_evidence e JOIN claims c ON c.id=e.claim_id
            JOIN users u ON u.id=c.author_user_id
            WHERE e.media_asset_id=m.id AND c.individual_id=i.id AND c.status='active'
            AND c.verification_status='positive' AND c.claim_type IN ('listing','media')
            AND u.ban_status='normal')''', (individual_id,)).fetchone()


def reverb_image_url(value):
    """Only the existing Reverb image CDN, never arbitrary or credentialed URLs."""
    from urllib.parse import urlsplit
    if not isinstance(value,str) or not value or len(value)>4096 or any(ord(c)<33 for c in value):return None
    try:
        url=urlsplit(value)
        if url.scheme!='https' or url.hostname not in ('images.reverb.com','photos.reverb.com','rvb-img.reverb.com') or url.port not in (None,443) or url.username or url.password or url.fragment or not url.path.startswith('/') or '\\' in value:return None
    except ValueError:return None
    return value


def initial_representative(con, individual_id):
    """Listing overview is public after acceptance; Acquire/closeups never are.

    Resolve from the accepted Listing so existing cloud registrations, whose
    public Media copy was omitted, work without rewriting their Evidence.
    """
    from ygc.cloud_applications import references
    import json
    row=con.execute('''SELECT a.images,a.image_meta FROM acquire_applications a
        JOIN claims c ON c.id=a.claim_id JOIN users u ON u.id=c.author_user_id
        WHERE c.individual_id=%s AND a.individual_id=c.individual_id
        AND a.request_kind='listing' AND a.status='accepted' AND c.claim_type='listing'
        AND c.status='active' AND c.verification_status='positive' AND u.ban_status='normal'
        ORDER BY c.id ASC LIMIT 1''',(individual_id,)).fetchone()
    if row:
        try:
            path=references(row).get('overview')
            return {'storage_path':path,'mime_type':'image/jpeg'} if path else None
        except (ValueError,TypeError,KeyError):return None
    rows=con.execute('''SELECT c.id,o.image_url AS legacy_image,o.source_site AS legacy_site,
        (SELECT li.value_text FROM claim_listing_items li WHERE li.claim_id=c.id AND li.field_name='image_url' ORDER BY li.id LIMIT 1) AS image_url,
        (SELECT li.value_text FROM claim_listing_items li WHERE li.claim_id=c.id AND li.field_name='source_site' ORDER BY li.id LIMIT 1) AS source_site,
        (SELECT e.payload_json FROM claim_source_evidence e WHERE e.claim_id=c.id AND e.evidence_type='marketplace_listing' ORDER BY e.id LIMIT 1) AS payload_json,
        (SELECT e.source_site FROM claim_source_evidence e WHERE e.claim_id=c.id AND e.evidence_type='marketplace_listing' ORDER BY e.id LIMIT 1) AS evidence_site
        FROM claims c JOIN users u ON u.id=c.author_user_id
        LEFT JOIN observations o ON o.id=c.observation_id
        WHERE c.individual_id=%s AND c.status='active' AND c.verification_status='positive'
        AND u.ban_status='normal' AND (c.claim_type='listing' OR
          (c.claim_type='ownership' AND c.ownership_kind='acquire' AND u.account_type='source'))
        ORDER BY substr(COALESCE(c.occurred_at,c.created_at),1,10) DESC,c.id DESC LIMIT 100''',(individual_id,)).fetchall()
    for row in rows:
        try:
            payload=json.loads(row['payload_json'] or '{}')
            source=payload.get('provenance') or payload.get('source') or {}
            if not isinstance(source,dict):source={}
        except (ValueError,TypeError,AttributeError):source={}
        site=row['evidence_site'] or row['source_site'] or row['legacy_site']
        url=reverb_image_url(row['image_url'] or source.get('image_url') or row['legacy_image'])
        if site=='reverb' and url:return {'remote_url':url}
    return None


def public_representative(con, individual_id):
    selected=representative(con,individual_id)
    return dict(selected) if selected else initial_representative(con,individual_id)
