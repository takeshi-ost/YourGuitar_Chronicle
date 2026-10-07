"""Private Listing-author Identity Correction, using the shared Observation rules.

No ownership authority is implied by this workflow. History is scoped to the
specified Listing and author; revisions include all identity inputs, regardless
of the displayed history page, to make stale and lost-response retries safe.
"""
from contextlib import contextmanager

from ygc import disputes
from ygc.cloud_claims import ClaimConnection, expected_revision
from ygc.claim_revision import ClaimConflict
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_ownership import digest, identifier, page
from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_ownership import BoundRepository, PostgresOwnership
from ygc.db.postgres_queries import ObservationConnection
from ygc.extractors.normalization import normalize_manufacturer, normalize_serial
from ygc.platform_boundaries import ActorContext

IDENTITY_FIELDS = ('manufacturer', 'model', 'year', 'serial_number')
LIMITS = {'manufacturer': 200, 'model': 200, 'year': 40, 'serial_number': 200, 'reason': 2000}


def payload(data):
    if not isinstance(data, dict) or set(data) != {'revision', *LIMITS}:
        raise ValueError('Missing or unknown Identity Correction field.')
    expected_revision(data)
    result = {'revision': data['revision']}
    for field, limit in LIMITS.items():
        value = data[field]
        if value is None and field in ('model', 'year', 'reason'):
            result[field] = None
            continue
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('Invalid Identity Correction field.')
        value.encode('utf-8')
        if any((ord(char) < 32 or ord(char) == 127) and
               not (field == 'reason' and char in '\n\r\t') for char in value):
            raise ValueError('Invalid Identity Correction field.')
        result[field] = value.strip() or None
    if not normalize_manufacturer(result['manufacturer']) or not normalize_serial(result['serial_number']):
        raise ValueError('Maker and Serial are required.')
    return result


def bounded_text(value, limit, *, multiline=False):
    # Historical data predates this API's input limits. Fail closed rather than
    # show truncated identity/old values that could silently become a new edit.
    if value is not None:
        if not isinstance(value, str) or len(value) > limit:
            raise RuntimeError('Stored Identity Correction is unavailable.')
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise RuntimeError('Stored Identity Correction is unavailable.') from None
        if any((ord(char) < 32 or ord(char) == 127) and
               not (multiline and char in '\n\r\t') for char in value):
            raise RuntimeError('Stored Identity Correction is unavailable.')
    return value


def own_listing(connection, listing, user):
    row = connection.execute("""SELECT c.* FROM claims c JOIN users u ON u.id=c.author_user_id
        JOIN individuals i ON i.id=c.individual_id WHERE c.id=? AND c.author_user_id=?
        AND c.claim_type='listing' AND c.status='active' AND u.ban_status='normal'
        AND u.account_type<>'source'""", (listing, user)).fetchone()
    if row is None:
        raise GuitarMissing()
    return row


def identity(connection, individual):
    row = connection.execute('SELECT id,' + ','.join(IDENTITY_FIELDS) +
                             ' FROM individuals WHERE id=?', (individual,)).fetchone()
    if row is None:
        raise GuitarMissing()
    return {'id': str(row['id']), **{key: bounded_text(row[key], LIMITS[key]) for key in IDENTITY_FIELDS}}


def identity_revision(connection, listing):
    individual = listing['individual_id']
    # Include inactive/negative history and full source rows. A second write in
    # the same timestamp, an admin decision, a Merge or a source edit must all
    # invalidate the old proposal even if the displayed identity is unchanged.
    claims = [dict(row) for row in connection.execute("""SELECT c.*,u.ban_status
        FROM claims c JOIN users u ON u.id=c.author_user_id WHERE c.individual_id=?
        AND c.claim_type IN ('listing','identity_correction') ORDER BY c.id""", (individual,))]
    items = {}
    for table in ('claim_listing_items', 'claim_identity_items'):
        items[table] = [dict(row) for row in connection.execute(f'''SELECT x.* FROM {table} x
            JOIN claims c ON c.id=x.claim_id WHERE c.individual_id=? ORDER BY x.id''', (individual,))]
    return digest({'listing': dict(listing), 'identity': identity(connection, individual),
                   'claims': claims, **items, 'disputes': [dict(row) for row in connection.execute(
                       'SELECT id,status,version FROM ownership_disputes WHERE individual_id=? ORDER BY id', (individual,))]})


def correction_projection(connection, row):
    if row['status'] not in ('active', 'inactive') or row['verification_status'] not in ('positive', 'negative', 'unverified'):
        raise RuntimeError('Stored Identity Correction is unavailable.')
    items = connection.execute("""SELECT field_name,old_value,new_value FROM claim_identity_items
        WHERE claim_id=? ORDER BY id LIMIT 5""", (row['id'],)).fetchall()
    seen, changes = set(), []
    if not 1 <= len(items) <= 4:
        raise RuntimeError('Stored Identity Correction is unavailable.')
    for item in items:
        field = item['field_name']
        if field not in IDENTITY_FIELDS or field in seen:
            raise RuntimeError('Stored Identity Correction is unavailable.')
        seen.add(field)
        changes.append({'field_name': field, **{key: bounded_text(item[key], LIMITS[field])
                                                for key in ('old_value', 'new_value')}})
    return {key: str(row[key]) for key in ('id', 'target_claim_id', 'individual_id')} | {
        'body': bounded_text(row['body'], LIMITS['reason'], multiline=True),
        'occurred_at': bounded_text(row['occurred_at'], 40), 'created_at': bounded_text(row['created_at'], 40),
        'status': row['status'], 'verification_status': row['verification_status'], 'changes': changes}


class CloudIdentityCorrections:
    def __init__(self, settings, operations):
        self.settings, self.operations = settings, operations

    @contextmanager
    def transaction(self, actor, listing=None, *, write=False):
        if listing is not None:
            identifier(listing)
        with connect(self.settings, 'operations') as guard:
            if write and not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise ClaimConflict('Maintenance or Crawl is running.')
            with self.operations.access('user_write' if write else 'user_read', actor) as (_, mode, account):
                if listing is None:
                    with PostgresAccounts(self.settings).content_transaction(actor, (account['id'],)) as (raw, canonical):
                        raw.execute("SET LOCAL statement_timeout='5s'")
                        raw.execute("SET LOCAL lock_timeout='2s'")
                        yield BoundRepository(ClaimConnection(raw)), canonical['id'], mode['mode'] != 'read_only'
                    return
                # Resolve only the author's active Listing before participant
                # discovery, so guessed IDs cannot expose hidden guitar state.
                with connect(self.settings, 'chronicle') as raw:
                    raw.execute("SET LOCAL statement_timeout='5s'")
                    raw.execute("SET LOCAL lock_timeout='2s'")
                    before = own_listing(ObservationConnection(raw), listing, account['id'])
                individual = before['individual_id']
                principal = ActorContext(account['id'], 'identity-platform', None, True, account['app_user_id'])
                with PostgresOwnership(self.settings)._transaction(principal, individual) as (bound, canonical):
                    connection = ClaimConnection(bound.connection.connection)
                    connection.execute("SET LOCAL statement_timeout='5s'")
                    connection.execute("SET LOCAL lock_timeout='2s'")
                    current = own_listing(connection, listing, canonical['id'])
                    if current['individual_id'] != individual:
                        raise ClaimConflict('Listing target changed; reload before retrying.')
                    # content_transaction owns the existing global content lock
                    # 79432002 until commit. Listing review, Crawl, projection,
                    # admin moderation and Merge use the same fence, so the
                    # Maker+Serial query and creation cannot race those writers.
                    yield BoundRepository(connection), canonical['id'], mode['mode'] != 'read_only'

    def list(self, actor, *, after=0, limit=25):
        page(after, limit)
        with self.transaction(actor) as (repo, user, can_write):
            rows = repo.connection.execute("""SELECT c.* FROM claims c JOIN users u ON u.id=c.author_user_id
                JOIN individuals i ON i.id=c.individual_id WHERE c.author_user_id=?
                AND c.claim_type='listing' AND c.status='active' AND u.ban_status='normal'
                AND u.account_type<>'source' AND (?=0 OR c.id<?) ORDER BY c.id DESC LIMIT ?""",
                (user, after, after, limit + 1)).fetchall()
            return {'items': [{'id': str(row['id']), 'individual': identity(repo.connection, row['individual_id']),
                               'occurred_at': bounded_text(row['occurred_at'], 40)} for row in rows[:limit]],
                    'next_after': str(rows[limit - 1]['id']) if len(rows) > limit else None,
                    'can_write': can_write}

    @staticmethod
    def _detail(connection, listing, user, can_write, *, after=0, limit=25):
        rows = connection.execute("""SELECT * FROM claims WHERE target_claim_id=? AND individual_id=?
            AND author_user_id=? AND claim_type='identity_correction' AND (?=0 OR id<?)
            ORDER BY id DESC LIMIT ?""", (listing['id'], listing['individual_id'], user, after, after, limit + 1)).fetchall()
        return {'listing': {'id': str(listing['id']), 'individual_id': str(listing['individual_id']),
                            'occurred_at': bounded_text(listing['occurred_at'], 40)},
                'individual': identity(connection, listing['individual_id']),
                'items': [correction_projection(connection, row) for row in rows[:limit]],
                'next_after': str(rows[limit - 1]['id']) if len(rows) > limit else None,
                'revision': identity_revision(connection, listing),
                'can_write': can_write and not bool(disputes.active(connection, listing['individual_id']))}

    def detail(self, actor, listing, *, after=0, limit=25):
        identifier(listing)
        page(after, limit)
        with self.transaction(actor, listing) as (repo, user, can_write):
            row = own_listing(repo.connection, listing, user)
            return self._detail(repo.connection, row, user, can_write, after=after, limit=limit)

    def create(self, actor, listing, data):
        identifier(listing)
        data = payload(data)
        with self.transaction(actor, listing, write=True) as (repo, user, can_write):
            row = own_listing(repo.connection, listing, user)
            if identity_revision(repo.connection, row) != data.pop('revision'):
                raise ClaimConflict('Identity changed; reload before retrying.')
            if disputes.active(repo.connection, row['individual_id']):
                raise ClaimConflict('Identity Correction is unavailable during an ownership dispute.')
            claim = repo.create_identity_correction(user, listing, **data)
            correction = repo.connection.execute('SELECT * FROM claims WHERE id=?', (claim,)).fetchone()
            return {'correction': correction_projection(repo.connection, correction),
                    'detail': self._detail(repo.connection, row, user, can_write)}
