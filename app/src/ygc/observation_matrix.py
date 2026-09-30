"""Read-only per-Claim proposals for the administrator Observation matrix."""

import json
import sqlite3

from ygc.observation_evaluator import FIELDS, ObservationEvaluation


def build_observation_matrix(
    con: sqlite3.Connection, individual_id: int, evaluated: ObservationEvaluation,
    saved: dict, current_specs: list[sqlite3.Row],
) -> dict:
    claims = con.execute(
        """SELECT c.*, u.display_name AS author_name FROM claims c
           JOIN users u ON u.id=c.author_user_id WHERE c.individual_id=?
           ORDER BY SUBSTR(COALESCE(c.occurred_at,''),1,10),c.id""",
        (individual_id,),
    ).fetchall()
    by_claim: dict[int, dict[str, object]] = {int(c['id']): {} for c in claims}

    def group_items(table: str, value_column: str) -> dict[int, dict]:
        return {
            int(cid): {row['field_name']: row[value_column] for row in con.execute(
                f"SELECT field_name,{value_column} FROM {table} WHERE claim_id=? ORDER BY id", (cid,))}
            for cid in by_claim
        }

    listing = group_items('claim_listing_items', 'value_text')
    identity = group_items('claim_identity_items', 'new_value')
    specifications = group_items('claim_spec_items', 'value_text')
    evidence = {int(row['claim_id']): row for row in con.execute(
        """SELECT e.* FROM claim_source_evidence e JOIN claims c ON c.id=e.claim_id
           WHERE c.individual_id=? AND e.evidence_type='marketplace_listing'
           ORDER BY e.id""", (individual_id,),
    )}
    user_ids = {str(items['owner_user_id']) for items in listing.values()
                if items.get('owner_user_id')}
    user_ids.update(str(c['value_text']) for c in claims
                    if c['claim_type'] == 'ownership' and c['value_text'])
    users = {}
    ids = sorted(user_ids)
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        marks = ','.join('?' for _ in chunk)
        users.update({str(u['id']): u for u in con.execute(
            'SELECT id,display_name,account_type,location_country,location_region '
            f'FROM users WHERE CAST(id AS TEXT) IN ({marks})', chunk,
        )})
    owner_fields = ('current_owner_name', 'current_owner_type',
                    'current_owner_user_id', 'current_owner_source_url')
    location_fields = ('location_country', 'location_region')

    def listing_owner(items: dict) -> dict:
        user_id = items.get('owner_user_id')
        owner = users.get(str(user_id)) if user_id else None
        return {
            'current_owner_name': owner['display_name'] if owner else items.get('owner_name'),
            'current_owner_type': owner['account_type'] if owner else items.get('owner_type'),
            'current_owner_user_id': str(user_id) if owner else None,
            'current_owner_source_url': items.get('source_url'),
        }

    for claim in claims:
        cid = int(claim['id'])
        proposals = by_claim[cid]
        items = listing[cid]
        kind = str(claim['ownership_kind'] or 'acquire')
        if claim['claim_type'] == 'listing':
            for field in ('manufacturer', 'model', 'finish', 'year', 'serial_number',
                          *location_fields):
                if items.get(field):
                    proposals[field] = items[field]
            proposals.update(listing_owner(items))
        elif claim['claim_type'] == 'identity_correction':
            proposals.update({field: value for field, value in identity[cid].items()
                              if field in ('manufacturer', 'model', 'year', 'serial_number')})
        elif claim['claim_type'] == 'specification':
            specs = specifications[cid]
            if claim['field_name'] and claim['value_text'] is not None:
                specs = {**specs, claim['field_name']: claim['value_text']}
            for field, value in specs.items():
                if field and value is not None:
                    proposals['finish' if field == 'finish' else 'spec:' + field] = value
        elif claim['claim_type'] == 'ownership':
            if claim['ownership_source'] == 'merged_listing':
                proposals.update(listing_owner(items))
                proposals.update({field: items.get(field) for field in location_fields})
            elif claim['ownership_source'] == 'user_transfer':
                owner = users.get(str(claim['value_text']))
                proposals.update({'current_owner_name':owner['display_name'] if owner else None,
                    'current_owner_type':owner['account_type'] if owner else None,
                    'current_owner_user_id':str(claim['value_text']), 'current_owner_source_url':None,
                    'location_country':owner['location_country'] if owner else None,
                    'location_region':owner['location_region'] if owner else None})
            elif kind in ('release', 'lost', 'transfer', 'inherit'):
                proposals.update({'current_owner_name': 'Unknown',
                                  'current_owner_type': 'unknown',
                                  'current_owner_user_id': None,
                                  'current_owner_source_url': None,
                                  'location_country': None, 'location_region': None})
            elif claim['ownership_source'] == 'automation':
                source = evidence.get(cid)
                if source:
                    try:
                        payload = json.loads(source['payload_json'] or '{}')
                        details = payload.get('claim', payload)
                    except (ValueError, TypeError, AttributeError):
                        details = {}
                    proposals.update({
                        'current_owner_name': details.get('owner_name') or 'Unknown',
                        'current_owner_type': details.get('owner_type') or 'unknown',
                        'current_owner_user_id': None,
                        'current_owner_source_url': source['source_url'],
                        'location_country': details.get('location_country'),
                        'location_region': details.get('location_region'),
                    })
            else:
                owner = users.get(str(claim['value_text']))
                proposals.update({
                    'current_owner_name': owner['display_name'] if owner else None,
                    'current_owner_type': owner['account_type'] if owner else None,
                    'current_owner_user_id': str(claim['value_text']) if owner else None,
                    'current_owner_source_url': None,
                    'location_country': owner['location_country'] if owner else None,
                    'location_region': owner['location_region'] if owner else None,
                })

    spec_fields = sorted({key for values in by_claim.values() for key in values
                          if key.startswith('spec:')})
    columns = ([{'key': key, 'group': 'individual'} for key in FIELDS] +
               [{'key': key, 'group': 'specification'} for key in spec_fields])
    spec_current = {'spec:' + row['field_name']: row['value_text']
                    for row in current_specs if row['field_name'] != 'finish'}
    sources = {**evaluated.sources,
               **{'spec:' + row['field_name']: int(row['claim_id'])
                  for row in current_specs if row['field_name'] != 'finish'}}
    current = {**saved, **spec_current}
    decisions: dict[int, list[dict]] = {}
    for decision in evaluated.decisions:
        decisions.setdefault(int(decision['claim_id']), []).append(decision)
    specification_evidence = {int(row['claim_id']): row for row in con.execute(
        """SELECT s.claim_id,s.source_site,s.source_listing_id
           FROM claim_specification_source s JOIN claims c ON c.id=s.claim_id
           WHERE c.individual_id=?""", (individual_id,),
    )}

    return {
        'columns': columns,
        'current': current,
        'rows': [{
            'claim_id': int(claim['id']), 'type': claim['claim_type'],
            'kind': claim['ownership_kind'] or claim['specification_kind'],
            'occurred_at': claim['occurred_at'], 'status': claim['status'],
            'verification_status': claim['verification_status'],
            'author_name': claim['author_name'],
            'decisions': decisions.get(int(claim['id']), []),
            'specification_evidence': (
                {'source_site': specification_evidence[int(claim['id'])]['source_site'],
                 'source_listing_id': specification_evidence[int(claim['id'])]['source_listing_id']}
                if int(claim['id']) in specification_evidence else None
            ),
            'cells': {field: {'value': value,
                              'adopted': sources.get(field) == int(claim['id'])}
                      for field, value in by_claim[int(claim['id'])].items()},
        } for claim in claims],
    }
