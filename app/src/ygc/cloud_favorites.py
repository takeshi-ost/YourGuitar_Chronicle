"""Canonical self-only favorites; visibility never grants another user access.

This relation conveys no ownership, Claim authority or public-profile data. The
only mutable table is user_favorites. Hidden/stale targets do not contribute to
pages or totals. Removing an ID is deliberately an idempotent self-only delete:
it reveals nothing about whether that target exists or remains public.
"""
from contextlib import ExitStack, contextmanager

from ygc.claim_revision import ClaimConflict
from ygc.cloud_guitars import GuitarMissing, MAX_ID
from ygc.cloud_public_catalog import (CLAIM_TYPES, STATES, COLUMNS, GUITAR_FIELDS,
                                      VISIBLE_GUITAR, guitar_projection, identifier)
from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.repository import utcnow


def decimal(value, *, zero=False):
    if (not isinstance(value, str) or len(value) > 19 or not value.isascii()
            or not value.isdecimal() or str(int(value)) != value
            or not (0 if zero else 1) <= int(value) <= MAX_ID):
        raise RuntimeError('Invalid favorite projection.')
    return value


def card_projection(row):
    if not isinstance(row, dict):
        raise RuntimeError('Invalid favorite guitar.')
    decimal(row.get('id'))
    for field in GUITAR_FIELDS:
        value = row.get(field)
        if value is not None:
            if not isinstance(value, str) or len(value) > 200:
                raise RuntimeError('Invalid favorite guitar.')
            value.encode('utf-8')
    return guitar_projection(row)


def result_projection(method, result):
    """Repeat the fixed response allowlist at the HTTP boundary."""
    if not isinstance(result, dict):
        raise RuntimeError('Invalid favorite response.')
    if method == 'list':
        items = result.get('items')
        if not isinstance(items, list) or len(items) > 50:
            raise RuntimeError('Invalid favorite page.')
        after = result.get('next_after')
        return {'items': [card_projection(row) for row in items],
                'total': decimal(result.get('total'), zero=True),
                'next_after': None if after is None else decimal(after)}
    if method not in ('detail', 'set') or type(result.get('favorite')) is not bool:
        raise RuntimeError('Invalid favorite state.')
    return {'individual_id': decimal(result.get('individual_id')), 'favorite': result['favorite']}


class CloudFavorites:
    def __init__(self, settings, operations):
        self.settings, self.operations = settings, operations

    @staticmethod
    def _participants(connection, user, individual=None):
        # Include excluded Claims too: a stale author BAN projection must never
        # make an otherwise hidden target visible. Never inspect another user's
        # favorites, owners, media, applications or private-profile fields.
        if individual is None:
            rows = connection.execute('''SELECT DISTINCT c.author_user_id FROM claims c
                JOIN user_favorites f ON f.individual_id=c.individual_id
                WHERE f.user_id=%s ORDER BY c.author_user_id''', (user,)).fetchall()
        else:
            rows = connection.execute('''SELECT DISTINCT author_user_id FROM claims
                WHERE individual_id=%s ORDER BY author_user_id''', (individual,)).fetchall()
        return {user} | {row['author_user_id'] for row in rows}

    @contextmanager
    def transaction(self, actor, *, individual=None, write=False, inspect_target=True):
        # Existing cross-database lock order: maintenance, service/account,
        # canonical participants, then Chronicle's shared projection/content
        # fence. Hold every guard until the content transaction commits.
        with connect(self.settings, 'operations') as guard:
            if write and not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise ClaimConflict('Maintenance or Crawl is running.')
            with self.operations.access('user_write' if write else 'user_read', actor) as (_, _, account):
                scope = {account['id']}
                target_read = inspect_target and individual is not None
                if target_read:
                    # First distinguish a broken self projection from target
                    # failures. This context closes before any additional
                    # canonical participant locks, preserving lock order.
                    with PostgresAccounts(self.settings).content_transaction(actor, scope) as (raw, canonical):
                        if canonical['id'] != account['id']:
                            raise PermissionError('Account participant mapping changed.')
                        raw.execute("SET LOCAL statement_timeout='5s'")
                        raw.execute("SET LOCAL lock_timeout='2s'")
                        self._visible(raw, individual)
                if inspect_target:
                    with connect(self.settings, 'chronicle') as raw:
                        raw.execute("SET LOCAL statement_timeout='5s'")
                        raw.execute("SET LOCAL lock_timeout='2s'")
                        scope = self._participants(raw, account['id'], individual)
                with self._content(actor, scope, target_read=target_read) as (raw, canonical):
                    if canonical['id'] != account['id']:
                        raise PermissionError('Account participant mapping changed.')
                    raw.execute("SET LOCAL statement_timeout='5s'")
                    raw.execute("SET LOCAL lock_timeout='2s'")
                    if inspect_target and not self._participants(raw, canonical['id'], individual).issubset(scope):
                        raise ClaimConflict('Favorite participants changed; reload.')
                    yield raw, canonical['id']

    @contextmanager
    def _content(self, actor, scope, *, target_read=False):
        with ExitStack() as stack:
            try:
                result = stack.enter_context(PostgresAccounts(self.settings).content_transaction(actor, scope))
            except ValueError:
                # Self was checked separately under the retained account lock.
                # Only entry failures from the target-author registry/projection
                # are indistinguishable from an unknown target.
                if target_read:
                    raise GuitarMissing() from None
                raise
            # Body and commit/rollback failures retain their original types,
            # including ClaimConflict, so callers can distinguish retryable races.
            yield result

    @staticmethod
    def _visible(connection, individual):
        if connection.execute(f'SELECT i.id FROM individuals i WHERE i.id=%s AND {VISIBLE_GUITAR}',
                              (individual, list(CLAIM_TYPES), list(STATES))).fetchone() is None:
            raise GuitarMissing()

    def list(self, actor, *, after=0, limit=25):
        if type(after) is not int or not 0 <= after <= MAX_ID or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Invalid favorite page.')
        with self.transaction(actor) as (con, user):
            where = f'f.user_id=%s AND {VISIBLE_GUITAR}'
            join = 'FROM user_favorites f JOIN individuals i ON i.id=f.individual_id'
            args = (user, list(CLAIM_TYPES), list(STATES))
            total = con.execute(f'SELECT COUNT(*) AS total {join} WHERE {where}', args).fetchone()['total']
            rows = con.execute(f'''SELECT {COLUMNS} {join} WHERE {where}
                AND (%s=0 OR i.id<%s) ORDER BY i.id DESC LIMIT %s''', (*args, after, after, limit + 1)).fetchall()
            return result_projection('list', {'items': [guitar_projection(row) for row in rows[:limit]],
                'total': str(total), 'next_after': str(rows[limit - 1]['id']) if len(rows) > limit else None})

    def detail(self, actor, individual):
        identifier(individual)
        with self.transaction(actor, individual=individual) as (con, user):
            self._visible(con, individual)
            exists = con.execute('SELECT 1 FROM user_favorites WHERE user_id=%s AND individual_id=%s',
                                 (user, individual)).fetchone() is not None
            return {'individual_id': str(individual), 'favorite': exists}

    def set(self, actor, individual, *, favorite):
        identifier(individual)
        if type(favorite) is not bool:
            raise ValueError('A Boolean favorite state is required.')
        with self.transaction(actor, individual=individual, write=True, inspect_target=favorite) as (con, user):
            if favorite:
                self._visible(con, individual)
                con.execute('''INSERT INTO user_favorites(user_id,individual_id,created_at)
                    VALUES(%s,%s,%s) ON CONFLICT(user_id,individual_id) DO NOTHING''',
                    (user, individual, utcnow()))
            else:
                # Do not read the target: false has exactly the same result for
                # public, hidden, deleted and unknown IDs, even when no row exists.
                con.execute('DELETE FROM user_favorites WHERE user_id=%s AND individual_id=%s', (user, individual))
            return {'individual_id': str(individual), 'favorite': favorite}
