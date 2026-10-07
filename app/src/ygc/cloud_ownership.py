"""Private, bounded Transfer and Release workflows for verified cloud accounts.

The shared Repository owns agreement, evidence, chronology and Observation.
This boundary adds live principal/mode/projection fences, privacy and opaque
compare-and-swap tokens without inventing a second ownership algorithm.
"""
from contextlib import contextmanager
import hashlib
import json
import re

from ygc import disputes
from ygc.claim_dates import validate_claim_date
from ygc.claim_revision import ClaimConflict
from ygc.cloud_guitars import GuitarMissing, MAX_ID, positive_id
from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_ownership import BoundRepository, PostgresOwnership
from ygc.db.postgres_queries import ObservationConnection
from ygc.db.repository import utcnow
from ygc.observation_evaluator import evaluate_observation
from ygc.platform_boundaries import ActorContext

GUITAR_FIELDS = ('manufacturer', 'model', 'finish', 'year', 'serial_number')
ACTION_STATES = {'accept': 'accepted', 'decline': 'declined', 'cancel': 'cancelled'}


def identifier(value):
    if type(value) is not int or not 0 < value <= MAX_ID:
        raise ValueError('Invalid identifier.')
    return value


def page(after, limit):
    if type(after) is not int or not 0 <= after <= MAX_ID or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('Invalid ownership page.')


def expected_revision(data):
    if not isinstance(data, dict) or not isinstance(data.get('revision'), str) or not re.fullmatch('[0-9a-f]{64}', data['revision']):
        raise ValueError('A current ownership revision is required.')
    return data['revision']


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


def person(connection, user):
    row = connection.execute('SELECT id,display_name,account_type FROM users WHERE id=?', (user,)).fetchone()
    return {'id': str(user), 'display_name': row['display_name'] if row else None,
            'account_type': row['account_type'] if row else None}


def guitar(connection, individual):
    row = connection.execute('SELECT id,' + ','.join(GUITAR_FIELDS) + ' FROM individuals WHERE id=?', (individual,)).fetchone()
    if row is None:
        raise GuitarMissing()
    return {'id': str(row['id']), **{key: row[key] for key in GUITAR_FIELDS}}


def transfer_row(connection, claim, user):
    row = connection.execute('''SELECT c.*,t.from_user_id,t.to_user_id,t.state,
        t.created_at AS transfer_created_at,t.resolved_at,e.accepted_by_user_id,
        e.accepted_at,e.current_owner_user_id AS accepted_current_owner_user_id
        FROM claims c JOIN claim_transfers t ON t.claim_id=c.id
        LEFT JOIN claim_transfer_acceptance e ON e.claim_id=c.id
        WHERE c.id=? AND (t.from_user_id=? OR t.to_user_id=?)''', (claim, user, user)).fetchone()
    if row is None:
        raise GuitarMissing()
    return row


def current_owner(connection, individual):
    owner = evaluate_observation(connection, individual).values['current_owner_user_id']
    return int(owner) if owner is not None else None


def account_facts(connection, ids):
    ids = sorted(set(value for value in ids if value is not None))
    if not ids:
        return []
    rows = [dict(row) for row in connection.execute('''SELECT id,app_user_id,display_name,
        account_type,ban_status,location_country,location_region,updated_at FROM users
        WHERE id IN (''' + ','.join('?' for _ in ids) + ') ORDER BY id', ids)]
    authority = getattr(connection, 'canonical_account_status', {})
    for row in rows:
        if row['id'] in authority:
            row.update(authority[row['id']])
    return rows


def ownership_revision(connection, individual):
    # Include proposal/history changes even while the owner stays the same.
    # Thus a lost create/Release response cannot be blindly repeated with the
    # old revision. Hash complete relevant records rather than only timestamps.
    snapshot = connection.execute('SELECT * FROM individuals WHERE id=?', (individual,)).fetchone()
    claims = [dict(row) for row in connection.execute("""SELECT * FROM claims
        WHERE individual_id=? AND claim_type IN ('listing','ownership','identity_correction') ORDER BY id""", (individual,))]
    transfers = [dict(row) for row in connection.execute('''SELECT t.* FROM claim_transfers t
        JOIN claims c ON c.id=t.claim_id WHERE c.individual_id=? ORDER BY t.claim_id''', (individual,))]
    evidence = [dict(row) for row in connection.execute('''SELECT e.* FROM claim_transfer_acceptance e
        JOIN claims c ON c.id=e.claim_id WHERE c.individual_id=? ORDER BY e.claim_id''', (individual,))]
    ids = {row['author_user_id'] for row in claims}
    for row in transfers:
        ids.update((row['from_user_id'], row['to_user_id']))
    if snapshot:
        ids.add(snapshot['current_owner_user_id'])
    return digest({'individual': dict(snapshot) if snapshot else None, 'claims': claims,
        'transfers': transfers, 'acceptance': evidence, 'accounts': account_facts(connection, ids),
        'source_evidence': [dict(row) for row in connection.execute('''SELECT e.* FROM claim_source_evidence e
            JOIN claims c ON c.id=e.claim_id WHERE c.individual_id=? ORDER BY e.id''', (individual,))],
        'listing_items': [dict(row) for row in connection.execute('''SELECT li.* FROM claim_listing_items li
            JOIN claims c ON c.id=li.claim_id WHERE c.individual_id=? ORDER BY li.id''', (individual,))],
        'dispute': [dict(row) for row in connection.execute(
            'SELECT id,status,version FROM ownership_disputes WHERE individual_id=? ORDER BY id', (individual,))]})


def transfer_projection(connection, row, user, can_write):
    individual = row['individual_id']
    owner = current_owner(connection, individual)
    accounts = account_facts(connection, (row['from_user_id'], row['to_user_id']))
    available = len(accounts) == 2 and all(item['account_type'] != 'source' and item['ban_status'] == 'normal' and not item.get('disabled', False) for item in accounts)
    pending = can_write and row['state'] == 'pending' and row['status'] == 'active'
    acceptance = None
    if row['accepted_by_user_id'] is not None:
        acceptance = {'accepted_by_user_id': str(row['accepted_by_user_id']),
            'accepted_at': row['accepted_at'], 'current_owner_user_id': str(row['accepted_current_owner_user_id'])}
    return {'id': str(row['id']), 'viewer_user_id': str(user), 'individual_id': str(individual), 'individual': guitar(connection, individual),
        'ownership_kind': 'transfer', 'from_user': person(connection, row['from_user_id']),
        'to_user': person(connection, row['to_user_id']), 'state': row['state'], 'status': row['status'],
        'verification_status': row['verification_status'], 'created_at': row['transfer_created_at'],
        'resolved_at': row['resolved_at'], 'occurred_at': row['occurred_at'], 'acceptance': acceptance,
        'can_accept': bool(pending and user == row['to_user_id'] and available
                           and owner == row['from_user_id'] and not disputes.active(connection, individual)),
        'can_decline': bool(pending and user == row['to_user_id']),
        'can_cancel': bool(pending and user == row['from_user_id']), 'can_write': can_write,
        'revision': digest({'claim': dict(row), 'owner': owner, 'accounts': accounts,
                            'ownership': ownership_revision(connection, individual)})}


def release_projection(row):
    return {'id': str(row['id']), 'individual_id': str(row['individual_id']),
        **{key: row[key] for key in ('ownership_kind', 'occurred_at', 'body', 'status',
            'verification_status', 'created_at', 'updated_at')}}


class CloudOwnership:
    def __init__(self, settings, operations):
        self.settings, self.operations = settings, operations

    def _account_status(self, connection, ids):
        # These same participant rows are already locked by content_transaction.
        # Role/disabled intentionally are not projected to Chronicle; consulting
        # the canonical rows keeps action flags and revision tokens current too.
        with connect(self.settings, 'accounts') as source:
            source.execute("SET LOCAL statement_timeout='5s'")
            rows = source.execute('''SELECT id,disabled,projection_version FROM account_records
                WHERE id=ANY(%s)''', (sorted(ids),)).fetchall()
        connection.canonical_account_status = {row['id']: {
            'disabled': bool(row['disabled']), 'projection_version': row['projection_version']} for row in rows}

    @staticmethod
    def _visible(connection, individual, user):
        row = connection.execute('''SELECT i.id FROM individuals i WHERE i.id=? AND (
            i.current_owner_user_id=? OR EXISTS (SELECT 1 FROM user_guitars ug
              WHERE ug.individual_id=i.id AND ug.user_id=?) OR EXISTS (
              SELECT 1 FROM claims c JOIN claim_transfers t ON t.claim_id=c.id
              WHERE c.individual_id=i.id AND (t.from_user_id=? OR t.to_user_id=?)))''',
            (individual, user, user, user, user)).fetchone()
        if not row:
            raise GuitarMissing()

    @contextmanager
    def transaction(self, actor, individual=None, *, claim=None, write=False, extra_ids=(), accept=False):
        if individual is not None:
            identifier(individual)
        if claim is not None:
            identifier(claim)
        with connect(self.settings, 'operations') as guard:
            if write and not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise ClaimConflict('Maintenance or Crawl is running.')
            with self.operations.access('user_write' if write else 'user_read', actor) as (_, mode, account):
                if account['ban_status'] != 'normal':
                    raise PermissionError('An active Transfer participant is required.')
                with connect(self.settings, 'chronicle') as raw:
                    raw.execute("SET LOCAL statement_timeout='5s'")
                    raw.execute("SET LOCAL lock_timeout='2s'")
                    check = ObservationConnection(raw)
                    participants = ()
                    if claim is not None:
                        before = transfer_row(check, claim, account['id'])
                        individual = before['individual_id']
                        participants = (before['from_user_id'], before['to_user_id'])
                    self._visible(check, individual, account['id'])
                principal = ActorContext(account['id'], 'identity-platform', None, True, account['app_user_id'])
                with PostgresOwnership(self.settings)._transaction(principal, individual, extra_ids,
                        active_ids=tuple(extra_ids) + (participants if accept else ())) as (repo, canonical):
                    repo.connection.execute("SET LOCAL statement_timeout='5s'")
                    repo.connection.execute("SET LOCAL lock_timeout='2s'")
                    self._visible(repo.connection, individual, canonical['id'])
                    self._account_status(repo.connection, PostgresOwnership._participants(repo.connection.connection, individual)
                                         | {canonical['id']} | set(extra_ids))
                    if claim is not None:
                        current = transfer_row(repo.connection, claim, canonical['id'])
                        if current['individual_id'] != individual or (current['from_user_id'], current['to_user_id']) != participants:
                            raise ClaimConflict('Transfer target changed; reload before retrying.')
                    yield repo, canonical['id'], mode['mode'] != 'read_only'

    @staticmethod
    def _inbox_rows(connection, user, after, limit):
        return connection.execute('''SELECT c.id,c.individual_id FROM claims c
            JOIN claim_transfers t ON t.claim_id=c.id
            WHERE (t.from_user_id=? OR t.to_user_id=?) AND (?=0 OR c.id<?)
            ORDER BY c.id DESC LIMIT ?''', (user, user, after, after, limit + 1)).fetchall()

    @contextmanager
    def inbox_transaction(self, actor, after, limit):
        with self.operations.access('user_read', actor) as (_, mode, account):
            if account['ban_status'] != 'normal':
                raise PermissionError('An active Transfer participant is required.')
            with connect(self.settings, 'chronicle') as raw:
                raw.execute("SET LOCAL statement_timeout='5s'")
                raw.execute("SET LOCAL lock_timeout='2s'")
                rows = self._inbox_rows(ObservationConnection(raw), account['id'], after, limit)
                scope = {account['id']}
                for individual in {row['individual_id'] for row in rows}:
                    scope.update(PostgresOwnership._participants(raw, individual))
            with PostgresAccounts(self.settings).content_transaction(actor, scope) as (raw, canonical):
                if canonical['id'] != account['id']:
                    raise PermissionError('Account participant mapping changed.')
                raw.execute("SET LOCAL statement_timeout='5s'")
                raw.execute("SET LOCAL lock_timeout='2s'")
                connection = ObservationConnection(raw)
                current = self._inbox_rows(connection, canonical['id'], after, limit)
                if [(r['id'], r['individual_id']) for r in current] != [(r['id'], r['individual_id']) for r in rows]:
                    raise ClaimConflict('Transfer inbox changed; reload.')
                for individual in {row['individual_id'] for row in current}:
                    if not PostgresOwnership._participants(raw, individual).issubset(scope):
                        raise ClaimConflict('Transfer participants changed; reload.')
                self._account_status(connection, scope)
                yield BoundRepository(connection), canonical['id'], mode['mode'] != 'read_only'

    def inbox(self, actor, *, after=0, limit=25):
        page(after, limit)
        with self.inbox_transaction(actor, after, limit) as (repo, user, can_write):
            rows = self._inbox_rows(repo.connection, user, after, limit)
            return {'viewer_user_id': str(user), 'can_write': can_write, 'items': [transfer_projection(repo.connection,
                transfer_row(repo.connection, row['id'], user), user, can_write) for row in rows[:limit]],
                'next_after': str(rows[limit - 1]['id']) if len(rows) > limit else None}

    def _view(self, repo, individual, user, can_write, after=0, limit=25):
        self._visible(repo.connection, individual, user)
        owner = current_owner(repo.connection, individual)
        allowed = can_write and owner == user and not disputes.active(repo.connection, individual)
        rows = repo.connection.execute('''SELECT c.* FROM claims c WHERE c.individual_id=?
            AND (?=0 OR c.id<?) AND ((c.claim_type='ownership' AND c.ownership_kind='release'
              AND c.author_user_id=?) OR EXISTS (SELECT 1 FROM claim_transfers t WHERE t.claim_id=c.id
              AND (t.from_user_id=? OR t.to_user_id=?))) ORDER BY c.id DESC LIMIT ?''',
            (individual, after, after, user, user, user, limit + 1)).fetchall()
        items = [transfer_projection(repo.connection, transfer_row(repo.connection, row['id'], user), user, can_write)
                 if row['ownership_kind'] == 'transfer' else release_projection(row) for row in rows[:limit]]
        return {'viewer_user_id': str(user), 'individual': guitar(repo.connection, individual),
            'current_owner_user_id': str(owner) if owner is not None else None,
            'is_current_owner': owner == user, 'can_write': can_write,
            'can_transfer': bool(allowed), 'can_release': bool(allowed),
            'revision': ownership_revision(repo.connection, individual), 'items': items,
            'next_after': str(rows[limit - 1]['id']) if len(rows) > limit else None}

    def view(self, actor, individual, *, after=0, limit=25):
        page(after, limit)
        with self.transaction(actor, individual) as (repo, user, can_write):
            return self._view(repo, individual, user, can_write, after, limit)

    def search_users(self, actor, individual, *, q='', offset=0, limit=20):
        if (not isinstance(q, str) or len(q) > 120 or any(ord(char) < 32 for char in q)
                or type(offset) is not int or not 0 <= offset <= 200
                or type(limit) is not int or not 1 <= limit <= 20):
            raise ValueError('Invalid destination search.')
        with self.transaction(actor, individual) as (repo, user, _):
            if current_owner(repo.connection, individual) != user:
                raise PermissionError('Only the Current Owner may search Transfer destinations.')
            term = q.strip()
            if not term:
                return {'items': [], 'next_offset': None}
            # Canonical active accounts, not a public profile or email directory.
            # Literal substring matching cannot turn '%' into a wildcard dump.
            with connect(self.settings, 'accounts') as con:
                con.execute("SET LOCAL statement_timeout='5s'")
                rows = con.execute('''SELECT id,display_name,account_type,app_user_id,projection_version FROM account_records
                    WHERE id<>%s AND account_type<>'source' AND ban_status='normal' AND disabled=0
                    AND (strpos(lower(display_name),lower(%s))>0 OR CAST(id AS TEXT)=%s)
                    ORDER BY lower(display_name),id LIMIT %s OFFSET %s''',
                    (user, term, term, limit + 1, offset)).fetchall()
            items = []
            for row in rows[:limit]:
                projected = repo.connection.execute('''SELECT u.id FROM users u
                    JOIN account_projection_receipts r ON r.account_id=u.id
                    WHERE u.id=? AND u.app_user_id=? AND r.app_user_id=? AND r.revision=?
                      AND u.display_name=? AND u.account_type=? AND u.ban_status='normal' ''',
                    (row['id'], row['app_user_id'], row['app_user_id'], row['projection_version'],
                     row['display_name'], row['account_type'])).fetchone()
                if projected:
                    items.append({'id': str(row['id']), 'display_name': row['display_name'],
                                  'account_type': row['account_type']})
            return {'items': items,
                'next_offset': offset + limit if len(rows) > limit and offset + limit <= 200 else None}

    @staticmethod
    def _compare_owner(repo, individual, user, expected):
        if ownership_revision(repo.connection, individual) != expected:
            raise ClaimConflict('Ownership changed; reload before retrying.')
        if current_owner(repo.connection, individual) != user:
            raise PermissionError('Only the Current Owner may change ownership.')
        disputes.guard(repo.connection, individual)
        repo._transfer_user(repo.connection, user)

    def create(self, actor, individual, data):
        expected = expected_revision(data)
        if set(data) != {'to_user_id', 'revision'}:
            raise ValueError('Invalid Transfer proposal.')
        target = positive_id(data['to_user_id'])
        with self.transaction(actor, individual, write=True, extra_ids=(target,)) as (repo, user, can_write):
            self._compare_owner(repo, individual, user, expected)
            if user == target:
                raise ValueError('Cannot transfer to yourself.')
            try:
                claim = repo.create_transfer_in_connection(repo.connection, user, individual, target)
            except ValueError as exc:
                if 'already pending' in str(exc):
                    raise ClaimConflict('A Transfer to this user is already pending.') from None
                raise
            return {'transfer': transfer_projection(repo.connection, transfer_row(repo.connection, claim, user), user, can_write)}

    def detail(self, actor, claim):
        with self.transaction(actor, claim=claim) as (repo, user, can_write):
            return transfer_projection(repo.connection, transfer_row(repo.connection, claim, user), user, can_write)

    def resolve(self, actor, claim, data):
        expected = expected_revision(data)
        if set(data) != {'action', 'revision'} or data['action'] not in ACTION_STATES:
            raise ValueError('Invalid Transfer response.')
        action = data['action']
        with self.transaction(actor, claim=claim, write=True, accept=action == 'accept') as (repo, user, can_write):
            row = transfer_row(repo.connection, claim, user)
            required = row['from_user_id'] if action == 'cancel' else row['to_user_id']
            if user != required:
                raise PermissionError('Only the designated participant may respond.')
            repo._transfer_user(repo.connection, user)
            # An identical terminal response is an idempotent read of the saved
            # agreement, even after an independent administrator verification.
            if row['state'] == ACTION_STATES[action]:
                return {'transfer': transfer_projection(repo.connection, row, user, can_write)}
            if row['state'] != 'pending' or row['status'] != 'active':
                raise ClaimConflict('Transfer is no longer pending.')
            if transfer_projection(repo.connection, row, user, can_write)['revision'] != expected:
                raise ClaimConflict('Transfer changed; reload before responding.')
            if action == 'accept':
                disputes.guard(repo.connection, row['individual_id'])
                if current_owner(repo.connection, row['individual_id']) != row['from_user_id']:
                    raise ClaimConflict('Current Owner changed; a new Transfer is required.')
            try:
                repo.resolve_transfer_in_connection(repo.connection, claim, user, action)
            except ValueError as exc:
                if 'chronology' in str(exc) or 'Current Owner changed' in str(exc):
                    raise ClaimConflict('Transfer conflicts with current ownership or chronology.') from None
                raise
            return {'transfer': transfer_projection(repo.connection, transfer_row(repo.connection, claim, user), user, can_write)}

    def release(self, actor, individual, data):
        expected = expected_revision(data)
        if set(data) != {'occurred_at', 'body', 'revision'}:
            raise ValueError('Invalid Release.')
        date, body = data['occurred_at'], data['body']
        if not isinstance(date, str) or not date.strip() or len(date) > 40:
            raise ValueError('A Release date is required.')
        date = validate_claim_date(date)
        if body is not None and (not isinstance(body, str) or len(body) > 2000 or '\x00' in body):
            raise ValueError('Invalid Release note.')
        body = body.strip() if body else None
        with self.transaction(actor, individual, write=True) as (repo, user, can_write):
            self._compare_owner(repo, individual, user, expected)
            _, claim = repo._create_ownership_claim_in_connection(repo.connection,
                user, individual, 'release', date, body, None, utcnow())
            row = repo.connection.execute('SELECT * FROM claims WHERE id=?', (claim,)).fetchone()
            return {'claim': release_projection(row), 'ownership': self._view(repo, individual, user, can_write)}
