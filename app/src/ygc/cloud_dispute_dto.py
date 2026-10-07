"""Explicit private ownership-dispute wire models and strict write payloads.

Identifiers stay decimal strings across JavaScript's safe integer boundary. No
row-to-JSON shortcut may expose a future column or the attachment BYTEA value.
"""
import re

from ygc.cloud_guitars import MAX_ID

# Response budgets are read-side safety limits, not restrictions on persisted
# rounds or administrative reconsideration. Oversized legacy history fails
# closed until a separately paginated history reader is available.
MAX_ROUNDS = 256
MAX_EVENTS = 1024
MAX_CLAIMS = MAX_EVIDENCE = 100
MAX_PARTIES = 200


def bounded(values, limit):
    if not isinstance(values, (list, tuple)) or len(values) > limit:
        raise RuntimeError('Dispute history exceeds the bounded detail reader.')
    return values


def decimal(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', value) or int(value) > MAX_ID:
        raise ValueError('A positive decimal-string identifier is required.')
    return int(value)


def wire_id(value):
    if type(value) is int and 0 < value <= MAX_ID:
        return str(value)
    decimal(value)
    return value


def text(value, limit, *, multiline=False, required=False, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Invalid dispute text.')
    value.encode('utf-8')
    if any((ord(c) < 32 or ord(c) == 127) and not (multiline and c in '\n\r\t') for c in value):
        raise ValueError('Invalid dispute text.')
    if required and not value.strip():
        raise ValueError('Required dispute text is empty.')
    return value


def revision(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('A current dispute option revision is required.')
    return value


def fields(data, keys):
    if not isinstance(data, dict) or set(data) != set(keys):
        raise ValueError('Missing or unknown dispute field.')


def acknowledgment_payload(data):
    fields(data, ('revision',))
    return {'revision': revision(data['revision'])}


def submission_payload(data):
    fields(data, ('revision', 'case_id', 'version', 'round_number', 'explanation', 'summary'))
    result = {key: text(data[key], limit, multiline=True, required=True).strip()
              for key, limit in (('explanation', 8000), ('summary', 4000))}
    if data['case_id'] is None:
        if data['version'] is not None or data['round_number'] is not None:
            raise ValueError('New appeals use a candidate revision.')
        result.update(revision=revision(data['revision']), case_id=None, version=None, round_number=None)
    else:
        if data['revision'] is not None:
            raise ValueError('Additional evidence uses the case version and round.')
        result.update(revision=None, **{key: decimal(data[key]) for key in ('case_id', 'version', 'round_number')})
    return result


def publication_payload(data):
    fields(data, ('version', 'round_number', 'summary'))
    return {'version': decimal(data['version']), 'round_number': decimal(data['round_number']),
            'summary': text(data['summary'], 4000, multiline=True, required=True).strip()}


def decision_payload(data):
    fields(data, ('version', 'round_number', 'action', 'reason', 'winner_claim_id'))
    action = data['action']
    if action not in ('owner', 'applicant', 'request_evidence', 'reopen'):
        raise ValueError('Invalid dispute decision.')
    winner = decimal(data['winner_claim_id']) if action == 'applicant' else None
    if action != 'applicant' and data['winner_claim_id'] is not None:
        raise ValueError('Only an applicant decision accepts a winning Claim.')
    return {'version': decimal(data['version']), 'round_number': decimal(data['round_number']),
            'action': action, 'reason': text(data['reason'], 4000, multiline=True, required=True).strip(),
            'winner_claim_id': winner}


def flag(value):
    if type(value) is not bool:
        raise ValueError('Invalid dispute capability.')
    return value


def nullable_id(value):
    return None if value is None else wire_id(value)


def stamp(value):
    return text(value, 50, nullable=True)


def person(value):
    if value is None:
        return None
    return {'id': wire_id(value['id']), 'display_name': text(value['display_name'], 200, nullable=True),
            'account_type': text(value['account_type'], 40, nullable=True)}


def guitar(value):
    return {'id': wire_id(value['id']), **{key: text(value[key], 1000, nullable=True)
            for key in ('manufacturer', 'model', 'finish', 'year', 'serial_number')}}


def option_projection(value):
    decline = value['decline']
    result = {'claim_id': wire_id(value['claim_id']), 'individual': guitar(value['individual']),
              'applicant': person(value['applicant']), 'owner': person(value['owner']),
              'requested_at': stamp(value['requested_at']), 'verification_status': value['verification_status'],
              'decline': None if decline is None else {
                  'reason': text(decline['reason'], 4000, multiline=True),
                  'created_at': stamp(decline['created_at']), 'acknowledged_at': stamp(decline['acknowledged_at'])},
              'wait_until': stamp(value['wait_until']), 'wait_days': value['wait_days'],
              'revision': revision(value['revision']), 'case_id': nullable_id(value['case_id'])}
    if result['verification_status'] not in ('positive', 'negative', 'unverified'):
        raise ValueError('Invalid verification status.')
    if type(result['wait_days']) is not int or result['wait_days'] < 1:
        raise ValueError('Invalid dispute waiting period.')
    return result | {key: flag(value[key]) for key in ('eligible', 'can_acknowledge', 'can_appeal', 'can_write')}


def case_projection(value):
    result = {key: wire_id(value[key]) for key in ('id', 'individual_id', 'owner_id', 'locked_owner_id', 'version', 'round_number')}
    result.update(winner_id=nullable_id(value['winner_id']), status=value['status'], decision=value['decision'],
                  created_at=stamp(value['created_at']), updated_at=stamp(value['updated_at']),
                  reason=text(value['reason'], 4000, multiline=True, nullable=True),
                  individual=guitar(value['individual']), owner=person(value['owner']),
                  current_owner=person(value['current_owner']), applicants=[person(p) for p in bounded(value['applicants'], MAX_CLAIMS)],
                  round_phase=value['round_phase'])
    if result['status'] not in ('open', 'resolved') or result['decision'] not in (None, 'owner', 'applicant'):
        raise ValueError('Invalid dispute state.')
    if result['round_phase'] not in ('collecting', 'reviewing'):
        raise ValueError('Invalid dispute phase.')
    return result


def round_projection(value):
    if value is None:
        return None
    if value['phase'] not in ('collecting', 'reviewing'):
        raise ValueError('Invalid dispute round phase.')
    return {'id': wire_id(value['id']), 'number': wire_id(value['number']), 'phase': value['phase'],
            'request_reason': text(value['request_reason'], 4000, multiline=True), 'created_at': stamp(value['created_at']),
            'parties': [{**{key: wire_id(p[key]) for key in ('claim_id', 'user_id')},
                        'display_name': text(p['display_name'], 200, nullable=True),
                        'submitted_at': stamp(p['submitted_at']), 'can_submit': flag(p['can_submit'])}
                       for p in bounded(value['parties'], MAX_PARTIES)]}


def detail_projection(value):
    result = case_projection(value)
    result.update(viewer_user_id=wire_id(value['viewer_user_id']), can_write=flag(value['can_write']),
                  is_admin=flag(value['is_admin']), can_reopen=flag(value['can_reopen']),
                  round=round_projection(value['round']), rounds=[round_projection(r) for r in bounded(value['rounds'], MAX_ROUNDS)],
                  claims=[{'claim_id': wire_id(c['claim_id']), 'applicant_id': wire_id(c['applicant_id']),
                           'applicant_name': text(c['applicant_name'], 200, nullable=True),
                           'decline_reason': text(c['decline_reason'], 4000, multiline=True, nullable=True),
                           'requested_at': stamp(c['requested_at'])} for c in bounded(value['claims'], MAX_CLAIMS)])
    allowed = {c['claim_id'] for c in result['claims']}
    evidence = []
    for row in bounded(value['evidence'], MAX_EVIDENCE):
        if wire_id(row['claim_id']) not in allowed:
            continue
        private = result['is_admin'] or wire_id(row['author_id']) == result['viewer_user_id']
        if not private and row['published_at'] is None:
            continue
        item = {key: wire_id(row[key]) for key in ('id', 'claim_id', 'author_id', 'round_number')}
        item.update(author_name=text(row['author_name'], 200, nullable=True), created_at=stamp(row['created_at']),
                    published_summary=text(row['published_summary'], 4000, multiline=True, nullable=True),
                    published_at=stamp(row['published_at']), can_publish=flag(row['can_publish']) and result['is_admin'])
        if private:
            item.update(explanation=text(row['explanation'], 8000, multiline=True),
                        summary=text(row['summary'], 4000, multiline=True),
                        filename=text(row['filename'], 255, nullable=True),
                        content_type=text(row['content_type'], 100, nullable=True), has_attachment=flag(row['has_attachment']))
        evidence.append(item)
    result['evidence'] = evidence
    result['events'] = [{'id': wire_id(e['id']), 'kind': text(e['kind'], 40),
                         'note': text(e['note'], 4500, multiline=True), 'created_at': stamp(e['created_at']),
                         'round_number': wire_id(e['round_number'])} for e in bounded(value['events'], MAX_EVENTS)]
    return result


def result_projection(method, result):
    """Defense in depth at HTTP dispatch; never serialize arbitrary service keys."""
    if method in ('options', 'list'):
        projection = option_projection if method == 'options' else case_projection
        return {'items': [projection(row) for row in bounded(result['items'], 50)],
                'next_after': nullable_id(result['next_after']), 'can_write': flag(result['can_write']),
                'viewer_user_id': wire_id(result['viewer_user_id'])}
    if method == 'option':
        return option_projection(result)
    if method == 'detail':
        return detail_projection(result)
    if method == 'acknowledge':
        return {'option': option_projection(result['option'])}
    if method in ('submit', 'publish', 'decide', 'decision'):
        return {'detail': detail_projection(result['detail'])}
    raise ValueError('Unknown dispute response.')


def request_projection(method, data):
    """Validate at HTTP ingress while retaining the strict wire representation."""
    validators = {'acknowledge': acknowledgment_payload, 'submit': submission_payload,
                  'publish': publication_payload, 'decide': decision_payload}
    if method not in validators:
        raise ValueError('Unknown dispute mutation.')
    validators[method](data)
    return dict(data)
