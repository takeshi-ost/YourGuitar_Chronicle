"""Read-only, one-per-Individual Observation evaluation for migration diagnostics.

A Claim is an assertion; source Evidence belongs to that Claim. This evaluator
never modifies the Individual and never persists a historical decision trace.
It runs alongside the legacy snapshot writer until parity has been checked.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


FIELDS = (
    'manufacturer', 'model', 'finish', 'year', 'serial_number',
    'location_country', 'location_region', 'current_owner_name',
    'current_owner_type', 'current_owner_user_id', 'current_owner_source_url',
)


@dataclass
class ObservationEvaluation:
    individual_id: int
    values: dict[str, Any]
    sources: dict[str, int]
    decisions: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {'individual_id': self.individual_id, 'values': self.values,
                'sources': self.sources, 'decisions': self.decisions}


def _date_key(claim: sqlite3.Row) -> tuple[str, int]:
    # The event date, not submission time, controls chronology. Claim ID is
    # the only tie break within a calendar day. Missing dates are diagnosed.
    occurred = str(claim['occurred_at'] or '').strip()
    return occurred[:10], int(claim['id'])


def evaluate_observation(con: sqlite3.Connection, individual_id: int) -> ObservationEvaluation:
    if not con.execute('SELECT 1 FROM individuals WHERE id=?', (individual_id,)).fetchone():
        raise ValueError('Individual not found')
    claims = con.execute(
        """SELECT c.*, u.ban_status, u.display_name AS author_name
           FROM claims c JOIN users u ON u.id=c.author_user_id
           WHERE c.individual_id=? ORDER BY c.id""", (individual_id,),
    ).fetchall()
    state: dict[str, Any] = dict.fromkeys(FIELDS)
    sources: dict[str, int] = {}
    decisions: list[dict[str, Any]] = []

    def set_value(field: str, value: Any, claim_id: int) -> None:
        state[field] = value
        sources[field] = claim_id

    def claim_items(table: str, claim_id: int, value_column: str = 'value_text') -> dict[str, Any]:
        if table not in ('claim_listing_items', 'claim_spec_items', 'claim_identity_items'):
            raise ValueError('Invalid item table')
        return {row['field_name']: row[value_column] for row in con.execute(
            f'SELECT field_name,{value_column} FROM {table} WHERE claim_id=? ORDER BY id',
            (claim_id,),
        )}

    first_listing: int | None = None
    identity = {'manufacturer', 'model', 'year', 'serial_number'}
    for claim in sorted((c for c in claims if c['claim_type'] == 'listing'), key=_date_key):
        cid = int(claim['id'])
        if claim['status'] != 'active':
            decisions.append({'claim_id': cid, 'type': 'listing', 'result': 'inactive'})
            continue
        items = claim_items('claim_listing_items', cid)
        for field in ('manufacturer', 'model', 'finish', 'year', 'serial_number',
                      'location_country', 'location_region'):
            value = items.get(field)
            if not value or (field not in identity and
                             (claim['verification_status'] != 'positive' or
                              claim['ban_status'] != 'normal')):
                continue
            if first_listing is None:
                first_listing = cid
            if cid == first_listing or (field in ('location_country', 'location_region') or
                                        state[field] is None):
                set_value(field, value, cid)
        decisions.append({'claim_id': cid, 'type': 'listing', 'result':
                          'accepted' if claim['verification_status'] == 'positive' and
                          claim['ban_status'] == 'normal' else 'identity_only'})

    for claim in sorted((c for c in claims if c['claim_type'] == 'identity_correction'), key=_date_key):
        cid = int(claim['id'])
        eligible = (claim['status'] == 'active' and claim['ban_status'] == 'normal'
                    and claim['verification_status'] == 'positive')
        if eligible:
            for field, value in claim_items('claim_identity_items', cid, 'new_value').items():
                if field in identity:
                    set_value(field, value.strip() if value else None, cid)
        decisions.append({'claim_id': cid, 'type': 'identity_correction', 'result':
                          'accepted' if eligible else 'not_effective'})

    for claim in sorted((c for c in claims if c['claim_type'] == 'specification'), key=_date_key):
        cid = int(claim['id'])
        eligible = (claim['status'] == 'active' and claim['ban_status'] == 'normal'
                    and claim['verification_status'] == 'positive')
        if eligible:
            finish = claim_items('claim_spec_items', cid).get('finish')
            if finish:
                set_value('finish', finish.strip(), cid)
        decisions.append({'claim_id': cid, 'type': 'specification', 'result':
                          'accepted' if eligible else 'not_effective'})

    for claim in sorted((c for c in claims if c['claim_type'] in ('listing', 'ownership')),
                        key=_date_key):
        cid = int(claim['id'])
        kind = claim['ownership_kind'] or 'acquire'
        if claim['status'] != 'active' or claim['ban_status'] != 'normal' or claim['verification_status'] != 'positive':
            decisions.append({'claim_id': cid, 'type': claim['claim_type'],
                              'result': 'not_effective', 'reason':
                              'inactive' if claim['status'] != 'active' else
                              'author_banned' if claim['ban_status'] != 'normal' else
                              'verification_' + str(claim['verification_status'])})
            continue
        if claim['claim_type'] == 'ownership' and not _date_key(claim)[0]:
            decisions.append({'claim_id': cid, 'type': 'ownership',
                              'result': 'not_effective', 'reason': 'missing_acquisition_date'})
            continue
        if claim['claim_type'] == 'listing' or claim['ownership_source'] == 'merged_listing':
            items = claim_items('claim_listing_items', cid)
            owner_id = items.get('owner_user_id')
            owner = con.execute('SELECT display_name,account_type FROM users WHERE id=?',
                                (owner_id,)).fetchone() if owner_id else None
            for field, value in {
                'current_owner_name': owner['display_name'] if owner else items.get('owner_name'),
                'current_owner_type': owner['account_type'] if owner else items.get('owner_type'),
                'current_owner_user_id': str(owner_id) if owner else None,
                'current_owner_source_url': items.get('source_url'),
            }.items():
                set_value(field, value, cid)
            if claim['ownership_source'] == 'merged_listing':
                for field in ('location_country', 'location_region'):
                    set_value(field, items.get(field), cid)
        elif claim['ownership_source'] == 'automation' and kind != 'release':
            evidence = con.execute(
                """SELECT * FROM claim_source_evidence
                   WHERE claim_id=? AND evidence_type='marketplace_listing' ORDER BY id LIMIT 1""",
                (cid,),
            ).fetchone()
            if evidence is None:
                decisions.append({'claim_id': cid, 'type': 'ownership',
                                  'result': 'not_effective', 'reason': 'missing_source_evidence'})
                continue
            payload = json.loads(evidence['payload_json'] or '{}')
            fields = payload.get('claim', payload)
            for field, value in {
                'current_owner_name': fields.get('owner_name') or 'Unknown',
                'current_owner_type': fields.get('owner_type') or 'unknown',
                'current_owner_user_id': None,
                'current_owner_source_url': evidence['source_url'],
                'location_country': fields.get('location_country'),
                'location_region': fields.get('location_region'),
            }.items():
                set_value(field, value, cid)
        elif kind in ('release', 'transfer', 'inherit'):
            for field, value in {
                'current_owner_name': 'Unknown', 'current_owner_type': 'unknown',
                'current_owner_user_id': None, 'current_owner_source_url': None,
                'location_country': None, 'location_region': None,
            }.items():
                set_value(field, value, cid)
        else:
            user = con.execute('SELECT display_name,account_type,location_country,location_region '
                               'FROM users WHERE id=?', (claim['value_text'],)).fetchone()
            for field, value in {
                'current_owner_name': user['display_name'] if user else None,
                'current_owner_type': user['account_type'] if user else None,
                'current_owner_user_id': str(claim['value_text']) if user else None,
                'current_owner_source_url': None,
                'location_country': user['location_country'] if user else None,
                'location_region': user['location_region'] if user else None,
            }.items():
                set_value(field, value, cid)
        decisions.append({'claim_id': cid, 'type': claim['claim_type'],
                          'result': 'accepted', 'event_date': _date_key(claim)[0]})
    return ObservationEvaluation(individual_id, state, sources, decisions)
