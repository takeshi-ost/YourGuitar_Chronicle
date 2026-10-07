"""Authenticated author's Specification/Incident CRUD using the shared Claim rules.

Only these two types are exposed here. Listing/Identity Correction/Ownership
and media consent have separate workflows. Reads return an author's complete
content privately; they do not expand the public catalog projection.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import re

from ygc.claim_dates import validate_claim_date, viewer_timezone
from ygc.claim_revision import ClaimConflict
from ygc.cloud_guitars import GuitarMissing, MAX_ID
from ygc.cloud_owner import specification_items, content_revision as claim_revision
from ygc.cloud_public_catalog import CLAIM_TYPES, GUITAR_FIELDS, STATES, identifier
from ygc.db.postgres import connect
from ygc.db.postgres_ownership import BoundRepository, PostgresOwnership
from ygc.db.postgres_queries import ObservationConnection, SharedCursor, qmark_parameters
from ygc.platform_boundaries import ActorContext

TYPES = ('specification', 'incident')


class ClaimConnection(ObservationConnection):
    """The bounded shared creation methods need generated IDs and item batches."""
    def execute(self, query, parameters=None):
        if re.match(r'\s*INSERT\s+INTO\s+(claims|notifications)\s*\(', query, re.I):
            cursor = self.connection.execute(qmark_parameters(query) + ' RETURNING id', parameters or ())
            result = SharedCursor(cursor)
            result.lastrowid = cursor.fetchone()['id']
            return result
        return super().execute(query, parameters)

    def executemany(self, query, parameters):
        with self.connection.cursor() as cursor:
            cursor.executemany(qmark_parameters(query), parameters)


def expected_revision(data):
    if not isinstance(data, dict) or not isinstance(data.get('revision'), str) or not re.fullmatch('[0-9a-f]{64}', data['revision']):
        raise ValueError('A current Claim revision is required.')
    return data['revision']


def payload(data, *, editing=False):
    if not isinstance(data, dict):
        raise ValueError('Invalid Claim.')
    common = {'claim_type', 'body', 'occurred_at'}
    allowed = common | ({'revision'} if editing else set())
    kind = data.get('claim_type')
    if kind == 'specification':
        allowed |= {'specification_kind', 'items'}
    elif kind == 'incident':
        allowed.add('incident_kind')
    else:
        raise ValueError('Unsupported Claim type.')
    if set(data) != allowed:
        raise ValueError('Missing or unknown Claim field.')
    if editing:
        expected_revision(data)
    result = dict(data)
    body = result['body']
    if body is not None and (not isinstance(body, str) or len(body) > 2000 or '\x00' in body):
        raise ValueError('Invalid Claim body.')
    result['body'] = body.strip() if body else None
    date = result['occurred_at']
    if date is not None and (not isinstance(date, str) or len(date) > 40):
        raise ValueError('Invalid Claim date.')
    result['occurred_at'] = validate_claim_date(date)
    if not editing and not result['occurred_at']:
        result['occurred_at'] = datetime.now(timezone.utc).astimezone(viewer_timezone.get()).date().isoformat()
    if kind == 'specification':
        if result['specification_kind'] not in ('specification', 'repair'):
            raise ValueError('Invalid Specification kind.')
        items = result['items']
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            raise ValueError('Invalid Specification items.')
        seen = set()
        normalized = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {'field_name', 'value_text'}:
                raise ValueError('Invalid Specification item.')
            for key, limit in (('field_name', 120), ('value_text', 500)):
                value = item[key]
                if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
                    raise ValueError('Invalid Specification item.')
            field = item['field_name'].strip().lower()
            if field in seen:
                raise ValueError('Duplicate Specification item.')
            seen.add(field)
            normalized.append(dict(field_name=field, value_text=item['value_text'].strip()))
        result['items'] = normalized
    elif result['incident_kind'] not in ('damage', 'lost', 'theft') or not result['body']:
        raise ValueError('Invalid Incident kind or detail.')
    return result


def own_projection(connection, row):
    return {'id': str(row['id']), 'individual_id': str(row['individual_id']),
        **{key: row[key] for key in ('claim_type', 'specification_kind', 'field_name', 'value_text',
            'body', 'occurred_at', 'status', 'verification_status', 'created_at', 'updated_at')},
        'specification_kind': (row['specification_kind'] or 'specification') if row['claim_type'] == 'specification' else None,
        'incident_kind': row['value_text'] if row['claim_type'] == 'incident' else None,
        'spec_items': specification_items(connection, row), 'revision': claim_revision(connection, row)}


class CloudClaims:
    def __init__(self, settings, operations):
        self.settings, self.operations = settings, operations

    @contextmanager
    def transaction(self, actor, individual, *, write=False):
        identifier(individual)
        with connect(self.settings, 'operations') as guard:
            if write and not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise ClaimConflict('Maintenance or Crawl is running.')
            with self.operations.access('user_write' if write else 'user_read', actor) as (_, mode, account):
                # Hide absent and inaccessible IDs before participant discovery:
                # that discovery's projection checks must not become an oracle
                # for unpublished guitars. The authoritative check is repeated
                # inside the fenced content transaction below.
                with connect(self.settings, 'chronicle') as check:
                    check.execute("SET LOCAL statement_timeout='5s'")
                    check.execute("SET LOCAL lock_timeout='2s'")
                    self._individual(BoundRepository(ObservationConnection(check)), individual, account['id'])
                principal = ActorContext(account['id'], 'identity-platform', None, True, account['app_user_id'])
                with PostgresOwnership(self.settings)._transaction(principal, individual) as (repo, canonical):
                    connection = ClaimConnection(repo.connection.connection)
                    connection.execute("SET LOCAL statement_timeout='5s'")
                    connection.execute("SET LOCAL lock_timeout='2s'")
                    bound = BoundRepository(connection)
                    self._individual(bound, individual, canonical['id'])
                    yield bound, canonical['id'], mode['mode'] != 'read_only'

    @staticmethod
    def _individual(repo, individual, user):
        # A hidden/unpublished guitar cannot be discovered by enumerating this
        # private endpoint. Authors may still manage their inactive submissions.
        marks = ','.join('?' for _ in CLAIM_TYPES)
        states = ','.join('?' for _ in STATES)
        row = repo.connection.execute(f'''SELECT i.id,{','.join('i.' + field for field in GUITAR_FIELDS)}
            FROM individuals i WHERE i.id=? AND (EXISTS (
              SELECT 1 FROM claims c JOIN users u ON u.id=c.author_user_id
              WHERE c.individual_id=i.id AND c.status='active' AND u.ban_status='normal'
                AND c.claim_type IN ({marks}) AND c.verification_status IN ({states}))
              OR EXISTS (SELECT 1 FROM claims c WHERE c.individual_id=i.id
                AND c.author_user_id=? AND c.claim_type IN ('specification','incident')))''',
            (individual, *CLAIM_TYPES, *STATES, user)).fetchone()
        if not row:
            raise GuitarMissing()
        return {'id': str(row['id']), **{field: row[field] for field in GUITAR_FIELDS}}

    def list(self, actor, individual, *, after=0, limit=25):
        if type(after) is not int or not 0 <= after <= MAX_ID or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Invalid Claim page.')
        with self.transaction(actor, individual) as (repo, user, can_write):
            guitar = self._individual(repo, individual, user)
            rows = repo.connection.execute('''SELECT * FROM claims WHERE individual_id=? AND author_user_id=?
                AND claim_type IN ('specification','incident') AND (?=0 OR id<?)
                ORDER BY id DESC LIMIT ?''', (individual, user, after, after, limit + 1)).fetchall()
            return {'individual': guitar, 'can_write': can_write,
                'items': [own_projection(repo.connection, row) for row in rows[:limit]],
                'next_after': str(rows[limit - 1]['id']) if len(rows) > limit else None}

    def create(self, actor, individual, data):
        data = payload(data)
        with self.transaction(actor, individual, write=True) as (repo, user, _):
            self._individual(repo, individual, user)
            if data['claim_type'] == 'specification':
                claim = repo.create_specification_claim_group(user, individual,
                    specification_kind=data['specification_kind'], items=data['items'],
                    occurred_at=data['occurred_at'], body=data['body'])
            else:
                claim = repo.create_incident_claim(user, individual, incident_kind=data['incident_kind'],
                    occurred_at=data['occurred_at'], detail=data['body'])
            repo.create_claim_notification(claim)
            return {'claim': own_projection(repo.connection, repo.connection.execute(
                'SELECT * FROM claims WHERE id=?', (claim,)).fetchone())}

    @staticmethod
    def _current(repo, individual, claim, user, expected):
        identifier(claim)
        row = repo.connection.execute('SELECT * FROM claims WHERE id=? FOR UPDATE', (claim,)).fetchone()
        if not row or row['individual_id'] != individual or row['author_user_id'] != user or row['claim_type'] not in TYPES:
            raise GuitarMissing()
        if row['status'] != 'active' or claim_revision(repo.connection, row) != expected:
            raise ClaimConflict('Claim changed or became inactive; reload before retrying.')
        return row

    def edit(self, actor, individual, claim, data):
        data = payload(data, editing=True)
        with self.transaction(actor, individual, write=True) as (repo, user, _):
            row = self._current(repo, individual, claim, user, data['revision'])
            if data['claim_type'] != row['claim_type']:
                raise ValueError('Claim type cannot change.')
            if row['claim_type'] == 'specification':
                updated = repo.update_specification_claim_group(claim, user,
                    specification_kind=data['specification_kind'], items=data['items'],
                    occurred_at=data['occurred_at'], body=data['body'])
            else:
                if data['incident_kind'] != row['value_text']:
                    raise ValueError('Incident kind cannot change.')
                updated = repo.update_claim(claim, user, occurred_at=data['occurred_at'], body=data['body'])
            if not updated:
                raise ClaimConflict('Claim is no longer active.')
            return {'claim': own_projection(repo.connection, repo.connection.execute(
                'SELECT * FROM claims WHERE id=?', (claim,)).fetchone())}

    def deactivate(self, actor, individual, claim, data):
        expected = expected_revision(data)
        if set(data) != {'revision'}:
            raise ValueError('Invalid deactivation.')
        with self.transaction(actor, individual, write=True) as (repo, user, _):
            self._current(repo, individual, claim, user, expected)
            if not repo.deactivate_claim(claim, user):
                raise ClaimConflict('Claim is no longer active.')
            return {'claim': own_projection(repo.connection, repo.connection.execute(
                'SELECT * FROM claims WHERE id=?', (claim,)).fetchone())}
