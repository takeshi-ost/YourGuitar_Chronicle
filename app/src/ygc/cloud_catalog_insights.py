"""Public catalog activity and aggregates, without private profile projections."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import re

from ygc.cloud_public_catalog import (CLAIM_TYPES, STATES, VISIBLE_CLAIM,
    VISIBLE_GUITAR, COLUMNS, guitar_projection)
from ygc.db.postgres import connect


def count(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError('Invalid aggregate count.')
    return str(value)


def distribution(rows):
    return [{'label': row['label'], 'count': count(row['count'])} for row in rows]


def chart_years(rows):
    values = Counter()
    for row in rows:
        label = re.sub(r'circa|c\.ha', '', str(row['label']), flags=re.IGNORECASE).strip()
        if re.fullmatch(r'[0-9]{4}', label):
            values[label] += row['count']
    return [{'label': label, 'count': count(values[label])} for label in sorted(values)]


def discoveries(catalog, actor):
    # One row per public guitar. Evidence timestamps are usable only through
    # their visible Claim; never return Evidence payloads, URLs, or private IDs.
    with catalog._read(actor) as con:
        rows = con.execute(f'''WITH visible AS (
            SELECT c.id,c.individual_id,c.claim_type,c.created_at,c.observation_id
            FROM claims c JOIN users u ON u.id=c.author_user_id WHERE {VISIBLE_CLAIM}),
            latest AS (SELECT DISTINCT ON (individual_id) individual_id,id,claim_type,created_at
                FROM visible ORDER BY individual_id,created_at DESC,id DESC),
            sources AS (
                SELECT c.individual_id,e.captured_at AS at FROM visible c
                JOIN claim_source_evidence e ON e.claim_id=c.id
                WHERE e.evidence_type='marketplace_listing' AND e.source_site<>'user'
                AND e.source_listing_id IS NOT NULL
                UNION ALL
                SELECT c.individual_id,o.observed_at FROM visible c
                JOIN observations o ON o.id=c.observation_id
                WHERE o.source_site<>'user' AND o.source_listing_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM claim_source_evidence e
                    WHERE e.evidence_type='marketplace_listing' AND e.claim_id=c.id)),
            captured AS (SELECT individual_id,MAX(at) AS at FROM sources GROUP BY individual_id)
            SELECT {COLUMNS},l.claim_type,l.created_at,
                GREATEST(l.created_at,COALESCE(s.at,'')) AS activity_at,
                CASE WHEN COALESCE(s.at,'')>l.created_at THEN 'discovery' ELSE 'claim' END AS activity_type
            FROM individuals i JOIN latest l ON l.individual_id=i.id
            LEFT JOIN captured s ON s.individual_id=i.id
            ORDER BY activity_at DESC,l.id DESC,i.id DESC LIMIT 200''',
            (list(CLAIM_TYPES), list(STATES))).fetchall()
        return {'items': [{**guitar_projection(row), 'activity_at': row['activity_at'],
            'activity_type': row['activity_type'],
            'claim_type': row['claim_type'] if row['activity_type'] == 'claim' else None} for row in rows]}


def statistics(catalog, actor):
    today = datetime.now(timezone.utc).date()
    first = today - timedelta(days=29)
    args = (list(CLAIM_TYPES), list(STATES))
    with catalog._read(actor) as con:
        total = con.execute(f'SELECT COUNT(*) AS count FROM individuals i WHERE {VISIBLE_GUITAR}', args).fetchone()['count']
        models = con.execute(f'''SELECT COALESCE(NULLIF(btrim(i.model),''),'Unknown') AS label,COUNT(*) AS count
            FROM individuals i WHERE {VISIBLE_GUITAR} GROUP BY label
            ORDER BY count DESC,COALESCE(NULLIF(btrim(i.model),''),'Unknown') COLLATE "C" ASC''', args).fetchall()
        if len(models) > 10:
            models = models[:10] + [{'label': 'Other', 'count': sum(row['count'] for row in models[10:])}]
        years = con.execute(f'''SELECT i.year AS label,COUNT(*) AS count FROM individuals i
            WHERE {VISIBLE_GUITAR} AND i.year IS NOT NULL GROUP BY i.year''', args).fetchall()
        listings = con.execute(f'''SELECT left(c.created_at,10) AS day,COUNT(*) AS count
            FROM claims c JOIN users u ON u.id=c.author_user_id
            WHERE {VISIBLE_CLAIM} AND c.claim_type='listing' AND left(c.created_at,10) BETWEEN %s AND %s
            GROUP BY day ORDER BY day''', (*args, first.isoformat(), today.isoformat())).fetchall()
        by_day = {row['day']: row['count'] for row in listings}
        return {'individuals': count(total), 'models': distribution(models), 'years': chart_years(years),
            'listings_30d': [{'date': (first + timedelta(days=offset)).isoformat(),
                'count': count(by_day.get((first + timedelta(days=offset)).isoformat(), 0))} for offset in range(30)]}


def world_map(catalog, actor):
    # A Chronicle snapshot can contain an old private residence. Registered
    # owners therefore use the canonical Accounts Public-country permission.
    # Group before returning: no owner/guitar IDs, region, or coordinates.
    with catalog._read(actor) as con:
        rows = con.execute(f'''SELECT i.current_owner_user_id AS owner_id,
            CASE WHEN i.current_owner_user_id IS NULL THEN NULLIF(btrim(i.location_country),'') END AS country,
            COUNT(*) AS count FROM individuals i WHERE {VISIBLE_GUITAR}
            GROUP BY i.current_owner_user_id,country''', (list(CLAIM_TYPES), list(STATES))).fetchall()
        ids = list({row['owner_id'] for row in rows if row['owner_id'] is not None})
        people = {}
        if ids:
            with connect(catalog.settings, 'accounts') as accounts:
                accounts.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                accounts.execute("SET LOCAL statement_timeout='5s'")
                accounts.execute("SET LOCAL lock_timeout='2s'")
                people = {row['id']: row['country'] for row in accounts.execute('''SELECT id,
                    NULLIF(btrim(location_country),'') AS country FROM account_records
                    WHERE id=ANY(%s) AND disabled=0 AND ban_status='normal' AND residence_visibility='Public' ''', (ids,)).fetchall()}
        values = Counter()
        for row in rows:
            country = people.get(row['owner_id']) if row['owner_id'] is not None else row['country']
            if country:
                values[country] += row['count']
        return {'countries': [{'country': name, 'count': count(values[name])}
            for name in sorted(values, key=lambda name: (-values[name], name))]}
