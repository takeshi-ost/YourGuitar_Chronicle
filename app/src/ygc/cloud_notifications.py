"""Recipient-only cloud inbox over existing notification history.

Pages use descending insertion IDs, independent of historical created_at text.
Reading history confers no Claim, Transfer or dispute authority. Typed destinations
are navigation hints only; the destination API must recheck current access. Every
read and write uses the same local visibility rule, with canonical account and
projection fences before names or stored messages can leave Chronicle.
"""
from contextlib import contextmanager

from ygc.claim_revision import ClaimConflict
from ygc.cloud_guitars import MAX_ID
from ygc.cloud_ownership import identifier, page
from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.postgres_queries import ObservationConnection
from ygc.db.repository import utcnow

# Exactly the local inbox's BAN/Silent BAN and inactive-Claim semantics. Keep one
# predicate for pagination, counts and both updates so hidden history never leaks
# through a badge or a guessed notification ID.
VISIBLE = """n.recipient_user_id=?
    AND (n.actor_user_id IS NULL OR actor.ban_status='normal')
    AND (n.claim_id IS NULL OR EXISTS (
        SELECT 1 FROM claims c JOIN users author ON author.id=c.author_user_id
        WHERE c.id=n.claim_id AND c.status='active' AND author.ban_status='normal'))"""
JOIN = 'FROM notifications n LEFT JOIN users actor ON actor.id=n.actor_user_id'
TEXT_LIMITS = {'notification_type': 64, 'title': 200, 'body': 8000,
               'created_at': 40, 'read_at': 40, 'display_name': 120}


class NotificationMissing(LookupError):
    pass


def text(value, field, *, nullable=False):
    """Plaintext, bounded complete values; do not silently truncate history."""
    if nullable and value is None:
        return None
    if not isinstance(value, str) or len(value) > TEXT_LIMITS[field]:
        raise RuntimeError('Stored notification is unavailable.')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise RuntimeError('Stored notification is unavailable.') from None
    if any((ord(char) < 32 or ord(char) == 127) and
           not (field == 'body' and char in '\n\r\t') for char in value):
        raise RuntimeError('Stored notification is unavailable.')
    return value


def decimal(value, *, zero=False):
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal()
            or len(value) > 19 or str(int(value)) != value
            or not (0 if zero else 1) <= int(value) <= MAX_ID):
        raise RuntimeError('Invalid notification projection.')
    return value


def destination_projection(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeError('Invalid notification destination.')
    if value.get('kind') == 'transfer':
        return {'kind': 'transfer', 'claim_id': decimal(value.get('claim_id'))}
    if value.get('kind') == 'owner':
        return {'kind': 'owner', 'individual_id': decimal(value.get('individual_id')),
                'claim_id': decimal(value.get('claim_id'))}
    raise RuntimeError('Invalid notification destination.')


def item_projection(row):
    """Defense-in-depth response allowlist, also used by the HTTP router."""
    actor = row.get('actor')
    if actor is not None:
        if not isinstance(actor, dict):
            raise RuntimeError('Invalid notification actor.')
        actor = {'id': decimal(actor.get('id')), 'display_name': text(actor.get('display_name'), 'display_name')}
    if type(row.get('is_read')) is not bool:
        raise RuntimeError('Invalid notification read state.')
    return {'id': decimal(row.get('id')),
            'notification_type': text(row.get('notification_type'), 'notification_type'),
            'title': text(row.get('title'), 'title'), 'body': text(row.get('body'), 'body', nullable=True),
            'created_at': text(row.get('created_at'), 'created_at'),
            'is_read': row['is_read'], 'read_at': text(row.get('read_at'), 'read_at', nullable=True),
            'actor': actor, 'destination': destination_projection(row.get('destination'))}


def result_projection(method, result):
    """Never serialize arbitrary service/database keys, even on future changes."""
    if not isinstance(result, dict):
        raise RuntimeError('Invalid notification response.')
    count = decimal(result.get('unread_count'), zero=True)
    if method in ('list', 'unread_count'):
        if type(result.get('can_write')) is not bool:
            raise RuntimeError('Invalid notification response.')
        projected = {'unread_count': count, 'can_write': result['can_write']}
        if method == 'list':
            items = result.get('items')
            if not isinstance(items, list) or len(items) > 50:
                raise RuntimeError('Invalid notification page.')
            after = result.get('next_after')
            projected.update(items=[item_projection(row) for row in items],
                             next_after=None if after is None else decimal(after))
        return projected
    if method == 'mark_read':
        if result.get('is_read') is not True:
            raise RuntimeError('Invalid notification read result.')
        return {'id': decimal(result.get('id')), 'is_read': True,
                'read_at': text(result.get('read_at'), 'read_at'), 'unread_count': count}
    if method == 'mark_all_read':
        return {'marked_count': decimal(result.get('marked_count'), zero=True), 'unread_count': count}
    raise RuntimeError('Invalid notification response.')


class CloudNotifications:
    def __init__(self, settings, operations):
        self.settings, self.operations = settings, operations

    @staticmethod
    def _participants(connection, user):
        # Discover from recipient-owned rows only, including currently hidden
        # rows: a stale projected BAN must not silently change the list/count.
        rows = connection.execute('''SELECT participant FROM (
            SELECT n.actor_user_id AS participant FROM notifications n WHERE n.recipient_user_id=?
            UNION SELECT c.author_user_id FROM notifications n JOIN claims c ON c.id=n.claim_id WHERE n.recipient_user_id=?
            UNION SELECT i.current_owner_user_id FROM notifications n JOIN individuals i ON i.id=n.individual_id WHERE n.recipient_user_id=?
            UNION SELECT t.from_user_id FROM notifications n JOIN claim_transfers t ON t.claim_id=n.claim_id WHERE n.recipient_user_id=?
            UNION SELECT t.to_user_id FROM notifications n JOIN claim_transfers t ON t.claim_id=n.claim_id WHERE n.recipient_user_id=?
            ) participants WHERE participant IS NOT NULL ORDER BY participant''',
            (user, user, user, user, user)).fetchall()
        return {user} | {row['participant'] for row in rows}

    @contextmanager
    def transaction(self, actor, *, write=False):
        # Preserve established lock order: maintenance, mode/account, canonical
        # participants, then Chronicle's shared content/projection fence.
        with connect(self.settings, 'operations') as guard:
            if write and not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise ClaimConflict('Maintenance or Crawl is running.')
            with self.operations.access('user_write' if write else 'user_read', actor) as (_, mode, account):
                with connect(self.settings, 'chronicle') as raw:
                    raw.execute("SET LOCAL statement_timeout='5s'")
                    raw.execute("SET LOCAL lock_timeout='2s'")
                    scope = self._participants(ObservationConnection(raw), account['id'])
                with PostgresAccounts(self.settings).content_transaction(actor, scope) as (raw, canonical):
                    if canonical['id'] != account['id']:
                        raise PermissionError('Account participant mapping changed.')
                    raw.execute("SET LOCAL statement_timeout='5s'")
                    raw.execute("SET LOCAL lock_timeout='2s'")
                    connection = ObservationConnection(raw)
                    if not self._participants(connection, canonical['id']).issubset(scope):
                        raise ClaimConflict('Notification participants changed; reload.')
                    yield BoundRepository(connection), canonical['id'], mode['mode'] != 'read_only'

    @staticmethod
    def _count(connection, user):
        return str(connection.execute(f'SELECT COUNT(*) AS count {JOIN} WHERE {VISIBLE} AND n.is_read=0',
                                      (user,)).fetchone()['count'])

    @staticmethod
    def _destination(repo, row, user, eligible):
        claim, individual = row['claim_id'], row['individual_id']
        if claim is None or individual is None:
            return None
        if row['notification_type'] in ('transfer_request', 'transfer_result'):
            participant = repo.connection.execute('''SELECT 1 FROM claim_transfers t JOIN claims c ON c.id=t.claim_id
                WHERE t.claim_id=? AND c.individual_id=? AND c.status='active'
                  AND (t.from_user_id=? OR t.to_user_id=?)''', (claim, individual, user, user)).fetchone()
            return {'kind': 'transfer', 'claim_id': str(claim)} if participant else None
        if row['notification_type'] in ('claim_added', 'claim_review'):
            if individual not in eligible:
                eligible[individual] = repo.owner_verifiable_claim_ids(individual, user)
            if claim in eligible[individual]:
                return {'kind': 'owner', 'individual_id': str(individual), 'claim_id': str(claim)}
        return None

    def list(self, actor, *, after=0, limit=25):
        page(after, limit)
        with self.transaction(actor) as (repo, user, can_write):
            rows = repo.connection.execute(f'''SELECT n.id,n.actor_user_id,n.notification_type,n.individual_id,
                n.claim_id,n.title,n.body,n.is_read,n.created_at,n.read_at,actor.display_name AS actor_name
                {JOIN} WHERE {VISIBLE} AND (?=0 OR n.id<?) ORDER BY n.id DESC LIMIT ?''',
                (user, after, after, limit + 1)).fetchall()
            eligible, items = {}, []
            for row in rows[:limit]:
                if row['is_read'] not in (0, 1):
                    raise RuntimeError('Stored notification read state is unavailable.')
                items.append(item_projection({'id': str(row['id']),
                    **{key: row[key] for key in ('notification_type', 'title', 'body', 'created_at', 'read_at')},
                    'is_read': bool(row['is_read']),
                    'actor': {'id': str(row['actor_user_id']), 'display_name': row['actor_name']}
                             if row['actor_user_id'] is not None else None,
                    'destination': self._destination(repo, row, user, eligible)}))
            return {'items': items, 'next_after': str(rows[limit - 1]['id']) if len(rows) > limit else None,
                    'unread_count': self._count(repo.connection, user), 'can_write': can_write}

    def unread_count(self, actor):
        with self.transaction(actor) as (repo, user, can_write):
            return {'unread_count': self._count(repo.connection, user), 'can_write': can_write}

    def mark_read(self, actor, notification):
        identifier(notification)
        with self.transaction(actor, write=True) as (repo, user, _):
            row = repo.connection.execute(f'SELECT n.id {JOIN} WHERE {VISIBLE} AND n.id=?',
                                          (user, notification)).fetchone()
            if row is None:
                raise NotificationMissing()
            # Reading must never acknowledge an ownership decline or invoke any
            # Claim/Transfer/dispute handler. Preserve the first read timestamp.
            repo.connection.execute('''UPDATE notifications SET is_read=1,read_at=COALESCE(read_at,?)
                WHERE id=? AND recipient_user_id=?''', (utcnow(), notification, user))
            updated = repo.connection.execute('SELECT read_at FROM notifications WHERE id=? AND recipient_user_id=?',
                                              (notification, user)).fetchone()
            return {'id': str(notification), 'is_read': True, 'read_at': text(updated['read_at'], 'read_at'),
                    'unread_count': self._count(repo.connection, user)}

    def mark_all_read(self, actor):
        with self.transaction(actor, write=True) as (repo, user, _):
            result = repo.connection.execute(f'''UPDATE notifications SET is_read=1,read_at=COALESCE(read_at,?)
                WHERE recipient_user_id=? AND is_read=0 AND id IN (
                    SELECT n.id {JOIN} WHERE {VISIBLE})''', (utcnow(), user, user))
            return {'marked_count': str(result.rowcount), 'unread_count': self._count(repo.connection, user)}
